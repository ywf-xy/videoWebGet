<script setup lang="ts">
/**
 * 数据源新增 / 编辑抽屉（PRD 6.7 / T17-③）：
 * 必填项（名称 / 类型 / 主地址）+ 备用地址动态增删 + 选择器配置 JSON + 自定义脚本 + 小说类开关。
 * 保存前：字段级校验 → URL 格式校验 → （编辑态且有脚本时）后端语法校验。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import ScriptEditor from '@/components/datasource/ScriptEditor.vue'
import { fetchDataSource, validateScript } from '@/api/dataSource'
import { useDataSourceStore } from '@/stores/dataSource'
import { SOURCE_TYPE_OPTIONS } from '@/utils/constants'
import type { DataSourcePayload, DataSourceUpdatePayload, SourceType } from '@/api/types'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    sourceId?: number | null
    defaultType?: string
  }>(),
  { sourceId: null, defaultType: 'video' },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'saved', id: number, isCreate: boolean): void
}>()

const store = useDataSourceStore()

interface FormState {
  name: string
  type: SourceType
  category: string
  homepage_url: string
  alt_urls: string[]
  script: string
  script_entry: string
  configText: string
  is_novel: boolean
  enabled: boolean
  notes: string
}

function emptyForm(type: SourceType = 'video'): FormState {
  return {
    name: '',
    type,
    category: '',
    homepage_url: '',
    alt_urls: [],
    script: '',
    script_entry: 'parse',
    configText: '',
    is_novel: false,
    enabled: true,
    notes: '',
  }
}

const form = reactive<FormState>(emptyForm())
const errors = reactive<Record<string, string>>({})
const loading = ref(false)
const saving = ref(false)
const scriptChecking = ref(false)
const scriptHint = ref('')
const showScript = ref(false)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const isEdit = computed(() => props.sourceId !== null && props.sourceId !== undefined)
const title = computed(() => (isEdit.value ? '编辑数据源' : '新增数据源'))

const configPlaceholder = `{
  "list_url": "https://example.com/list?page={page}",
  "item_selector": ".list li",
  "link_selector": "a@href",
  "title_selector": "a@text",
  "detail_content_selector": "#content",
  "detail_video_selector": "video@src",
  "detail_image_selector": ".gallery img@src"
}`

function resetForm(type: SourceType = 'video'): void {
  Object.assign(form, emptyForm(type))
  Object.keys(errors).forEach((key) => delete errors[key])
  scriptHint.value = ''
  showScript.value = false
}

async function loadDetail(id: number): Promise<void> {
  loading.value = true
  try {
    const detail = await fetchDataSource(id)
    form.name = detail.name
    form.type = detail.type as SourceType
    form.category = detail.category ?? ''
    form.homepage_url = detail.homepage_url
    form.alt_urls = [...detail.alt_urls]
    form.script = detail.script ?? ''
    form.script_entry = detail.script_entry || 'parse'
    form.configText = Object.keys(detail.config_json ?? {}).length
      ? JSON.stringify(detail.config_json, null, 2)
      : ''
    form.is_novel = detail.is_novel
    form.enabled = detail.enabled
    form.notes = detail.notes ?? ''
    showScript.value = Boolean(detail.script)
  } catch {
    ElMessage.error('数据源详情加载失败')
  } finally {
    loading.value = false
  }
}

function addAltUrl(): void {
  form.alt_urls.push('')
}

function removeAltUrl(index: number): void {
  form.alt_urls.splice(index, 1)
}

function isHttpUrl(value: string): boolean {
  return /^https?:\/\/[^\s]+$/i.test(value.trim())
}

function validate(): boolean {
  Object.keys(errors).forEach((key) => delete errors[key])

  if (!form.name.trim()) errors.name = '请填写数据源名称'
  if (!form.homepage_url.trim()) {
    errors.homepage_url = '请填写主地址'
  } else if (!isHttpUrl(form.homepage_url)) {
    errors.homepage_url = '地址必须以 http:// 或 https:// 开头'
  }

  form.alt_urls.forEach((url, index) => {
    if (url.trim() && !isHttpUrl(url)) {
      errors[`alt_${index}`] = '备用地址格式不正确'
    }
  })

  if (form.configText.trim()) {
    try {
      const parsed = JSON.parse(form.configText)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        errors.configText = '配置必须是 JSON 对象（{...}）'
      }
    } catch {
      errors.configText = 'JSON 格式不合法，请检查括号与引号'
    }
  }

  return Object.keys(errors).length === 0
}

function buildPayload(): DataSourcePayload | DataSourceUpdatePayload {
  let config: Record<string, unknown> = {}
  if (form.configText.trim()) {
    try {
      config = JSON.parse(form.configText) as Record<string, unknown>
    } catch {
      config = {}
    }
  }
  const altUrls = form.alt_urls.map((url) => url.trim()).filter(Boolean)
  return {
    name: form.name.trim(),
    type: form.type,
    category: form.category.trim() || null,
    homepage_url: form.homepage_url.trim(),
    alt_urls: altUrls,
    script: form.script.trim() ? form.script : null,
    script_entry: form.script_entry || 'parse',
    config_json: config,
    is_novel: form.type === 'text' ? form.is_novel : false,
    enabled: form.enabled,
    notes: form.notes.trim() || null,
  }
}

async function handleSave(): Promise<void> {
  if (!validate()) {
    ElMessage.warning('请先修正表单中的错误')
    return
  }

  // 编辑态且填了脚本：保存前做后端语法校验（P1-02）
  if (isEdit.value && form.script.trim() && props.sourceId) {
    scriptChecking.value = true
    try {
      const result = await validateScript(props.sourceId, form.script, form.script_entry)
      if (!result.valid) {
        scriptHint.value = result.line
          ? `第 ${result.line} 行：${result.message}`
          : result.message
        ElMessage.error('脚本语法检查未通过，已阻止保存')
        return
      }
      scriptHint.value = ''
    } finally {
      scriptChecking.value = false
    }
  }

  saving.value = true
  try {
    const payload = buildPayload()
    const id = await store.save(isEdit.value ? (props.sourceId as number) : null, payload)
    ElMessage.success(isEdit.value ? '已保存修改' : '数据源创建成功')
    emit('saved', id, !isEdit.value)
    visible.value = false
  } finally {
    saving.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    if (isEdit.value && props.sourceId) {
      void loadDetail(props.sourceId)
    } else {
      resetForm((props.defaultType as SourceType) ?? 'video')
    }
  },
)

watch(
  () => form.type,
  (next) => {
    if (next !== 'text') form.is_novel = false
  },
)
</script>

<template>
  <el-drawer v-model="visible" :title="title" size="640px" :destroy-on-close="true">
    <div v-loading="loading" class="source-form">
      <el-form label-width="96px" label-position="right">
        <el-form-item label="名称" required :error="errors.name">
          <el-input v-model="form.name" placeholder="例如：某某影视站" maxlength="100" show-word-limit />
        </el-form-item>

        <el-form-item label="类型" required>
          <el-radio-group v-model="form.type">
            <el-radio-button
              v-for="option in SOURCE_TYPE_OPTIONS"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="分类">
          <el-input v-model="form.category" placeholder="参与产物目录命名，如：科幻" maxlength="100" />
          <div class="source-form__tip">留空时产物目录使用「未分类」</div>
        </el-form-item>

        <el-form-item label="主地址" required :error="errors.homepage_url">
          <el-input v-model="form.homepage_url" placeholder="https://example.com/list" />
        </el-form-item>

        <el-form-item label="备用地址">
          <div class="source-form__alt">
            <div v-for="(_, index) in form.alt_urls" :key="index" class="source-form__alt-row">
              <el-input v-model="form.alt_urls[index]" placeholder="https://backup.example.com/list" />
              <el-button text type="danger" @click="removeAltUrl(index)">
                <el-icon><Delete /></el-icon>
              </el-button>
              <span v-if="errors[`alt_${index}`]" class="source-form__script-error">
                {{ errors[`alt_${index}`] }}
              </span>
            </div>
            <el-button size="small" plain @click="addAltUrl">
              <el-icon><Plus /></el-icon>
              添加备用地址
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="选择器配置" :error="errors.configText">
          <el-input
            v-model="form.configText"
            type="textarea"
            :rows="8"
            :placeholder="configPlaceholder"
            class="source-form__json"
          />
          <div class="source-form__tip">
            用于内置解析器：<code>item_selector</code> 等 CSS 选择器；支持
            <code>css@attr</code>（attr 可为 text / html / href / src）
          </div>
        </el-form-item>

        <el-form-item v-if="form.type === 'text'" label="小说类">
          <el-switch v-model="form.is_novel" active-text="是" inactive-text="否" />
          <div class="source-form__tip">
            小说类产物路径为「数据源/分类/小说名/章节名.txt」，非小说为「数据源/分类/日期/文章名.txt」
          </div>
        </el-form-item>

        <el-form-item label="自定义脚本">
          <el-switch v-model="showScript" active-text="启用" inactive-text="关闭" />
          <div class="source-form__tip">
            启用后优先使用脚本解析；脚本入口函数签名 <code>def parse(args): ...</code>
          </div>
        </el-form-item>

        <template v-if="showScript">
          <el-form-item label="脚本入口">
            <el-input v-model="form.script_entry" placeholder="parse" style="width: 200px" />
          </el-form-item>
          <el-form-item label="脚本内容">
            <ScriptEditor v-model="form.script" height="260px" />
            <div v-if="scriptHint" class="source-form__script-error">{{ scriptHint }}</div>
            <div class="source-form__tip">
              保存前会做语法检查；「试运行」可在列表页操作列发起
              <template v-if="!isEdit">（新建数据源需先保存后才能服务端校验）</template>
            </div>
          </el-form-item>
        </template>

        <el-form-item label="启用状态">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving || scriptChecking" @click="handleSave">
        保存
      </el-button>
    </template>
  </el-drawer>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.source-form {
  &__tip {
    width: 100%;
    font-size: 12px;
    color: $color-text-secondary;
    line-height: 1.6;
    margin-top: 4px;

    code {
      background: $color-bg-page;
      padding: 1px 4px;
      border-radius: 2px;
      font-family: $font-mono;
    }
  }

  &__alt {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__alt-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__json {
    :deep(textarea) {
      font-family: $font-mono;
      font-size: 12px;
      line-height: 1.6;
    }
  }

  &__script-error {
    width: 100%;
    margin-top: 6px;
    color: $color-danger;
    font-size: 12px;
  }
}
</style>
