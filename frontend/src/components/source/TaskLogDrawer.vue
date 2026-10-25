<script setup lang="ts">
/**
 * 任务日志抽屉（PRD P1-07 / T16-⑦）：级别过滤 + 关键字搜索 + 自动滚动跟随。
 * 日志正文来自后端 task_log（用户可读业务日志，不含调试栈）。
 */
import { computed, nextTick, ref, watch } from 'vue'

import StatusTag from '@/components/common/StatusTag.vue'
import { LOG_LEVEL_OPTIONS } from '@/utils/constants'
import { formatBytes, formatDateTimeSeconds, formatDuration } from '@/utils/format'
import type { TaskDetail, TaskItem, TaskLogItem } from '@/api/types'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    task: TaskItem | null
    logs: TaskLogItem[]
    loading?: boolean
    /** 任务详情（可选，来自 GET /tasks/{id}） */
    detail?: TaskDetail | null
  }>(),
  { loading: false, detail: null },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'refresh', filters: { level: string; keyword: string }): void
}>()

const level = ref<string>('ALL')
const keyword = ref('')
const autoScroll = ref(true)
const logBox = ref<HTMLDivElement | null>(null)

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  return props.logs.filter((item) => {
    if (level.value !== 'ALL' && item.level !== level.value) return false
    if (key && !item.message.toLowerCase().includes(key)) return false
    return true
  })
})

function parts(message: string): { text: string; hit: boolean }[] {
  const key = keyword.value.trim()
  if (!key) return [{ text: message, hit: false }]
  const lowerMessage = message.toLowerCase()
  const lowerKey = key.toLowerCase()
  const result: { text: string; hit: boolean }[] = []
  let cursor = 0
  let index = lowerMessage.indexOf(lowerKey)
  while (index !== -1) {
    if (index > cursor) result.push({ text: message.slice(cursor, index), hit: false })
    result.push({ text: message.slice(index, index + key.length), hit: true })
    cursor = index + key.length
    index = lowerMessage.indexOf(lowerKey, cursor)
  }
  if (cursor < message.length) result.push({ text: message.slice(cursor), hit: false })
  return result
}

async function scrollToBottom(): Promise<void> {
  if (!autoScroll.value) return
  await nextTick()
  const element = logBox.value
  if (element) element.scrollTop = element.scrollHeight
}

function handleRefresh(): void {
  emit('refresh', { level: level.value, keyword: keyword.value })
  void scrollToBottom()
}

watch(
  () => [props.modelValue, props.logs.length],
  ([open]) => {
    if (open) void scrollToBottom()
  },
)

watch(level, handleRefresh)
watch(keyword, handleRefresh)
</script>

<template>
  <el-drawer v-model="visible" title="任务日志" size="620px" :destroy-on-close="false">
    <template #header>
      <div class="log-drawer__header">
        <div class="flex-center gap-8">
          <span class="log-drawer__title">任务日志</span>
          <StatusTag v-if="task" kind="task" :status="task.status" />
        </div>
        <span v-if="task" class="text-secondary log-drawer__sub">{{ task.title }}</span>
      </div>
    </template>

    <div class="log-drawer__toolbar">
      <el-select v-model="level" size="small" style="width: 110px">
        <el-option
          v-for="option in LOG_LEVEL_OPTIONS"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-input v-model="keyword" size="small" placeholder="搜索关键字" clearable style="width: 180px" />
      <el-checkbox v-model="autoScroll" size="small">自动滚动</el-checkbox>
      <el-button size="small" :loading="loading" @click="handleRefresh">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
      <span class="text-secondary log-drawer__count">{{ filtered.length }} 条</span>
    </div>

    <el-descriptions v-if="props.detail" :column="1" border size="small" class="mb-12">
      <el-descriptions-item label="源地址">
        <span class="ellipsis">{{ props.detail.source_url }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="耗时 / 重试">
        {{ formatDuration(props.detail.duration_ms) }} · 第 {{ props.detail.attempt_count }} 次
      </el-descriptions-item>
      <el-descriptions-item v-if="props.detail.result" label="产物">
        {{ formatBytes(props.detail.result.file_size) }} ·
        <span class="ellipsis">{{ props.detail.result.output_path }}</span>
      </el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="task?.error_msg"
      class="mb-12"
      type="error"
      :closable="false"
      show-icon
      :title="`[${task.error_code ?? '-'}] ${task.error_msg}`"
    />

    <div v-loading="loading" ref="logBox" class="log-window log-drawer__box">
      <template v-if="filtered.length > 0">
        <div v-for="item in filtered" :key="item.id" class="log-line">
          <span class="log-time">{{ formatDateTimeSeconds(item.created_at) }}</span>
          <span class="log-level" :class="`log-level--${item.level}`">{{ item.level }}</span>
          <span class="log-message">
            <template v-for="(part, index) in parts(item.message)" :key="index">
              <mark v-if="part.hit">{{ part.text }}</mark>
              <span v-else>{{ part.text }}</span>
            </template>
          </span>
        </div>
      </template>
      <div v-else class="log-empty">暂无日志{{ keyword ? '（或关键字无命中）' : '' }}</div>
    </div>
  </el-drawer>
</template>

<style scoped lang="scss">
.log-drawer {
  &__header {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &__title {
    font-size: 15px;
    font-weight: 600;
  }

  &__sub {
    font-size: 12px;
  }

  &__toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  &__count {
    font-size: 12px;
    margin-left: auto;
  }

  &__box {
    height: calc(100vh - 220px);
  }
}
</style>
