<script setup lang="ts">
/**
 * 设置页（PRD 6.8 / T18）：个人信息 / 采集设置 / 系统信息 / 危险操作 四区块。
 * 保存后线程数立即生效（后端 PUT /settings 会同步引擎并发上限）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import DangerZone from '@/components/setting/DangerZone.vue'
import PathTester from '@/components/setting/PathTester.vue'
import { useSettingStore } from '@/stores/setting'
import { LIMITS } from '@/utils/constants'
import { formatBytes } from '@/utils/format'
import type { UploadFile } from 'element-plus'

const store = useSettingStore()

const form = reactive({
  nickname: '',
  email: '',
  avatar: '',
  maxThreads: 4,
  outputRoot: '',
  maxAttempts: 3,
  baseInterval: 1,
  refreshInterval: 3600,
})

const avatarUploading = ref(false)
const savedAt = ref('')

const settings = computed(() => store.settings)
const systemInfo = computed(() => store.systemInfo)

const threadError = computed(() => {
  if (form.maxThreads < LIMITS.minThreads || form.maxThreads > LIMITS.maxThreads) {
    return `最大线程数需在 ${LIMITS.minThreads}-${LIMITS.maxThreads} 之间`
  }
  return ''
})

const canSave = computed(() => !threadError.value && form.outputRoot.trim().length > 0)

const ffmpegInfo = computed(() => systemInfo.value?.ffmpeg ?? null)
const ffmpegMissing = computed(() => ffmpegInfo.value !== null && !ffmpegInfo.value.available)

function fillForm(): void {
  const data = settings.value
  if (!data) return
  form.nickname = data.profile.nickname
  form.email = data.profile.email
  form.avatar = data.profile.avatar
  form.maxThreads = data.max_threads
  form.outputRoot = data.output_root
  form.maxAttempts = data.retry.max_attempts
  form.baseInterval = data.retry.base_interval
  form.refreshInterval = data.health.refresh_interval
}

async function handleSave(): Promise<void> {
  if (!canSave.value) {
    ElMessage.warning(threadError.value || '请填写输出根目录')
    return
  }
  await store.save({
    profile: { nickname: form.nickname || '采集者', email: form.email, avatar: form.avatar },
    max_threads: form.maxThreads,
    output_root: form.outputRoot.trim(),
    retry: { max_attempts: form.maxAttempts, base_interval: form.baseInterval },
    health: { refresh_interval: form.refreshInterval },
  })
  savedAt.value = new Date().toLocaleTimeString('zh-CN')
  ElMessage.success(`设置已保存，最大线程数 ${form.maxThreads} 立即生效`)
  fillForm()
}

/** 头像上传：自定义 http-request，走 setting store 的 multipart 接口 */
async function handleAvatarUpload(options: { file: File }): Promise<void> {
  avatarUploading.value = true
  try {
    const url = await store.uploadAvatar(options.file)
    form.avatar = url
    ElMessage.success('头像已更新')
  } finally {
    avatarUploading.value = false
  }
}

function handleAvatarChange(file: UploadFile): void {
  if (!file.raw) return
  void handleAvatarUpload({ file: file.raw })
}

function copyPath(path: string): void {
  if (!path) return
  // 非安全上下文（非 localhost / 非 https）下 clipboard 可能不存在，降级为提示
  if (!navigator.clipboard?.writeText) {
    ElMessage.warning(`当前环境不支持剪贴板，路径：${path}`)
    return
  }
  void navigator.clipboard
    .writeText(path)
    .then(() => ElMessage.success('路径已复制'))
    .catch(() => ElMessage.warning(`路径：${path}`))
}

onMounted(async () => {
  await Promise.all([store.load(), store.loadSystemInfo()])
  fillForm()
})
</script>

<template>
  <div class="page settings">
    <PageHeader title="设置" description="个人信息、采集并发与产物目录、系统信息与危险操作" icon="Setting">
      <template #extra>
        <span v-if="savedAt" class="text-secondary">上次保存：{{ savedAt }}</span>
        <el-button :loading="store.loading" @click="store.load().then(fillForm)">
          <el-icon><Refresh /></el-icon>
          重新加载
        </el-button>
        <el-button type="primary" :loading="store.saving" :disabled="!canSave" @click="handleSave">
          保存设置
        </el-button>
      </template>
    </PageHeader>

    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <!-- 个人信息 -->
        <div class="card">
          <div class="card-title">
            <div class="card-title__left"><span>个人信息</span></div>
          </div>
          <el-form label-width="90px">
            <el-form-item label="头像">
              <div class="settings__avatar">
                <el-avatar :size="64" :src="form.avatar || undefined">
                  {{ form.nickname.slice(0, 1) || 'C' }}
                </el-avatar>
                <el-upload
                  :auto-upload="false"
                  :show-file-list="false"
                  accept="image/png,image/jpeg"
                  :on-change="handleAvatarChange"
                >
                  <el-button size="small" :loading="avatarUploading">上传头像</el-button>
                </el-upload>
                <span class="text-secondary settings__hint">≤ 2MB，支持 png / jpg</span>
              </div>
            </el-form-item>
            <el-form-item label="昵称">
              <el-input v-model="form.nickname" placeholder="采集者" maxlength="30" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="form.email" placeholder="选填" />
            </el-form-item>
          </el-form>
        </div>

        <!-- 采集设置 -->
        <div class="card">
          <div class="card-title">
            <div class="card-title__left">
              <span>采集设置</span>
              <el-tag size="small" type="info" effect="plain">修改后新批次立即生效</el-tag>
            </div>
          </div>
          <el-form label-width="110px">
            <el-form-item label="最大线程数" :error="threadError">
              <div class="settings__thread">
                <el-slider
                  v-model="form.maxThreads"
                  :min="LIMITS.minThreads"
                  :max="LIMITS.maxThreads"
                  :step="1"
                  show-stops
                  style="width: 220px"
                />
                <el-input-number
                  v-model="form.maxThreads"
                  :min="LIMITS.minThreads"
                  :max="LIMITS.maxThreads"
                  size="small"
                  controls-position="right"
                  style="width: 110px"
                />
                <el-tag size="small" type="info" effect="plain">
                  当前占用 {{ store.systemInfo?.threads.active ?? 0 }}/{{ store.systemInfo?.threads.max ?? 0 }}
                </el-tag>
              </div>
            </el-form-item>

            <el-form-item label="输出根目录">
              <PathTester v-model="form.outputRoot" />
            </el-form-item>

            <el-form-item label="失败重试次数">
              <el-input-number v-model="form.maxAttempts" :min="1" :max="10" size="small" />
              <span class="text-secondary settings__hint">达到上限后不再自动重试</span>
            </el-form-item>

            <el-form-item label="重试间隔基数">
              <el-input-number v-model="form.baseInterval" :min="1" :max="60" size="small" />
              <span class="text-secondary settings__hint">实际间隔 = 基数 × 2^(n-1)，上限 30s</span>
            </el-form-item>
          </el-form>
        </div>
      </el-col>

      <el-col :xs="24" :md="12">
        <!-- 系统信息 -->
        <div class="card">
          <div class="card-title">
            <div class="card-title__left"><span>系统信息</span></div>
            <el-button link type="primary" size="small" :loading="store.systemLoading" @click="store.loadSystemInfo()">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>

          <el-descriptions v-if="systemInfo" :column="1" border size="small">
            <el-descriptions-item label="应用版本">{{ systemInfo.version }}</el-descriptions-item>
            <el-descriptions-item label="运行环境">{{ systemInfo.python }}</el-descriptions-item>
            <el-descriptions-item label="SQLite 文件">
              <div class="settings__path">
                <span class="ellipsis">{{ systemInfo.db_path }}</span>
                <span class="text-secondary">{{ formatBytes(systemInfo.db_size) }}</span>
                <el-button link type="primary" size="small" @click="copyPath(systemInfo.db_path)">
                  复制
                </el-button>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="输出根目录">
              <div class="settings__path">
                <span class="ellipsis">{{ systemInfo.output_root }}</span>
                <el-button link type="primary" size="small" @click="copyPath(systemInfo.output_root)">
                  复制
                </el-button>
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="ffmpeg">
              <el-tag v-if="!ffmpegInfo?.available" type="danger" effect="plain">未检测到</el-tag>
              <el-tag v-else type="success" effect="plain">已安装 {{ ffmpegInfo.version }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="线程占用">
              {{ systemInfo.threads.active }} / {{ systemInfo.threads.max }}
            </el-descriptions-item>
          </el-descriptions>

          <el-alert
            v-if="ffmpegMissing"
            class="mt-12"
            type="error"
            :closable="false"
            show-icon
            title="未检测到 ffmpeg，视频只能产出 .ts"
            description="m3u8 转 MP4 不可用：视频任务会标记失败(3003)，但分片会下载并以 .ts 保留。安装 ffmpeg 并加入 PATH 后重启后端即可。"
          />
        </div>

        <!-- 危险操作 -->
        <div class="card">
          <div class="card-title">
            <div class="card-title__left">
              <span class="text-danger">危险操作</span>
              <el-tag size="small" type="danger" effect="plain">需要二次确认</el-tag>
            </div>
          </div>
          <DangerZone @changed="store.loadSystemInfo()" />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.settings {
  &__avatar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  &__hint {
    font-size: 12px;
  }

  &__thread {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  &__path {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;

    .ellipsis {
      max-width: 320px;
    }
  }
}

.mt-12 {
  margin-top: 12px;
}
</style>
