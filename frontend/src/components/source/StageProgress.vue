<script setup lang="ts">
/**
 * 阶段反馈区（PRD 6.3.2 阶段反馈 / T16-⑤）：
 * 阶段一文案「解析列表中…」→「本次解析到 N 条」；阶段二进度条 + 成功/失败/跳过计数；
 * 实时日志窗口（等宽字体、级别着色、自动滚底、关键字高亮）。
 */
import { computed, nextTick, ref, watch } from 'vue'

import EmptyState from '@/components/common/EmptyState.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { LOG_LEVEL_OPTIONS } from '@/utils/constants'
import { formatDuration, formatNumber } from '@/utils/format'
import type { ActiveTaskItem, BatchLogItem, BatchProgressInfo } from '@/api/types'

const props = withDefaults(
  defineProps<{
    batch: BatchProgressInfo | null
    batchId: number | null
    active: ActiveTaskItem[]
    logs: BatchLogItem[]
    polling?: boolean
    busy?: boolean
    warnings?: string[]
    errorCode?: string | null
    errorMsg?: string | null
  }>(),
  { polling: false, busy: false, warnings: () => [], errorCode: null, errorMsg: null },
)

const emit = defineEmits<{
  (event: 'pause'): void
  (event: 'resume'): void
  (event: 'retry-failed'): void
  (event: 'refresh'): void
}>()

const level = ref<string>('ALL')
const keyword = ref('')
const logBox = ref<HTMLDivElement | null>(null)

const status = computed(() => props.batch?.status ?? '')
const phase = computed(() => props.batch?.phase ?? '')
const total = computed(() => props.batch?.total ?? 0)
const done = computed(() => props.batch?.done ?? 0)
const failed = computed(() => props.batch?.failed ?? 0)
const skipped = computed(() => props.batch?.skipped ?? 0)
const pending = computed(() => Math.max(0, total.value - done.value - failed.value))

const isRunning = computed(() => status.value === 'running' || status.value === 'pending')
const isPaused = computed(
  () => status.value === 'paused' || status.value === 'paused_with_warning',
)
const isTerminal = computed(() =>
  ['success', 'success_with_warning', 'failed'].includes(status.value),
)

const phaseText = computed(() => {
  if (!props.batchId) return ''
  if (phase.value === 'parse' && isRunning.value) return '正在解析列表…'
  if (phase.value === 'parse' && isTerminal.value) return '列表解析完成'
  if (total.value > 0) return `本次解析到 ${formatNumber(total.value)} 条`
  if (isTerminal.value) return '没有需要采集的新内容'
  return '准备中…'
})

const progressStatus = computed(() => {
  if (status.value === 'failed') return 'exception'
  if (status.value === 'success' || status.value === 'success_with_warning') return 'success'
  if (isPaused.value) return 'warning'
  return undefined
})

const filteredLogs = computed(() => {
  const key = keyword.value.trim().toLowerCase()
  return props.logs.filter((item) => {
    if (level.value !== 'ALL' && item.level !== level.value) return false
    if (key && !item.message.toLowerCase().includes(key)) return false
    return true
  })
})

/** 关键字高亮切片（避免 v-html） */
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

function scrollToBottom(): void {
  const element = logBox.value
  if (!element) return
  element.scrollTop = element.scrollHeight
}

watch(
  () => filteredLogs.value.length,
  async () => {
    await nextTick()
    scrollToBottom()
  },
)
</script>

<template>
  <div class="stage card">
    <div class="card-title">
      <div class="card-title__left">
        <span>执行进度</span>
        <StatusTag v-if="batchId" kind="batch" :status="status" />
        <el-tag v-if="polling" size="small" type="info" effect="plain">2s 自动刷新</el-tag>
      </div>
      <div class="flex-center gap-8">
        <el-button v-if="isRunning" size="small" type="warning" plain :loading="busy" @click="emit('pause')">
          <el-icon><VideoPause /></el-icon>
          暂停
        </el-button>
        <el-button v-if="isPaused" size="small" type="primary" :loading="busy" @click="emit('resume')">
          <el-icon><VideoPlay /></el-icon>
          继续
        </el-button>
        <el-button
          v-if="isTerminal && failed > 0"
          size="small"
          type="danger"
          plain
          :loading="busy"
          @click="emit('retry-failed')"
        >
          <el-icon><RefreshRight /></el-icon>
          重试失败项
        </el-button>
        <el-button size="small" :disabled="!batchId" @click="emit('refresh')">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <EmptyState
      v-if="!batchId"
      compact
      icon="Aim"
      title="尚未开始采集"
      description="选择策略后点击「开始爬取」，这里会显示实时进度与日志"
    />

    <template v-else>
      <div class="stage__headline">
        <span class="stage__phase">{{ phaseText }}</span>
        <span class="text-secondary">耗时 {{ formatDuration(batch?.elapsed_ms ?? 0) }}</span>
      </div>

      <el-progress
        :percentage="batch?.progress ?? 0"
        :status="progressStatus"
        :stroke-width="14"
        :text-inside="true"
        class="stage__progress"
      />

      <div class="stage__counters">
        <div class="stage__counter stage__counter--success">
          <span class="stage__counter-value">{{ formatNumber(done) }}</span>
          <span class="stage__counter-label">成功</span>
        </div>
        <div class="stage__counter stage__counter--danger">
          <span class="stage__counter-value">{{ formatNumber(failed) }}</span>
          <span class="stage__counter-label">失败</span>
        </div>
        <div class="stage__counter">
          <span class="stage__counter-value">{{ formatNumber(skipped) }}</span>
          <span class="stage__counter-label">跳过</span>
        </div>
        <div class="stage__counter">
          <span class="stage__counter-value">{{ formatNumber(pending) }}</span>
          <span class="stage__counter-label">待处理</span>
        </div>
        <div class="stage__counter">
          <span class="stage__counter-value">{{ formatNumber(total) }}</span>
          <span class="stage__counter-label">总数</span>
        </div>
      </div>

      <el-alert
        v-if="errorMsg"
        class="mb-12"
        type="error"
        :closable="false"
        show-icon
        :title="`[${errorCode ?? '错误'}] ${errorMsg}`"
      />

      <el-alert
        v-for="(warn, index) in warnings"
        :key="index"
        class="mb-8"
        type="warning"
        :closable="false"
        show-icon
        :title="warn"
      />

      <div v-if="active.length > 0" class="stage__active">
        <div class="stage__active-title text-secondary">正在执行（{{ active.length }}）</div>
        <div v-for="item in active" :key="item.task_id" class="stage__active-item">
          <span class="ellipsis">{{ item.title }}</span>
          <span class="text-secondary">{{ item.step_done }}/{{ item.step_total }}</span>
        </div>
      </div>

      <div class="stage__log-header">
        <span class="text-secondary">实时日志</span>
        <div class="flex-center gap-8">
          <el-select v-model="level" size="small" style="width: 96px">
            <el-option
              v-for="option in LOG_LEVEL_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-input v-model="keyword" size="small" placeholder="搜索日志" clearable style="width: 160px" />
        </div>
      </div>

      <div ref="logBox" class="log-window">
        <template v-if="filteredLogs.length > 0">
          <div v-for="item in filteredLogs" :key="item.id" class="log-line">
            <span class="log-time">{{ item.created_at.slice(11, 19) }}</span>
            <span class="log-level" :class="`log-level--${item.level}`">{{ item.level }}</span>
            <span class="log-message">
              <template v-for="(part, index) in parts(item.message)" :key="index">
                <mark v-if="part.hit">{{ part.text }}</mark>
                <span v-else>{{ part.text }}</span>
              </template>
            </span>
          </div>
        </template>
        <div v-else class="log-empty">暂无日志</div>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/variables.scss' as *;

.stage {
  &__headline {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    font-size: 13px;
  }

  &__phase {
    font-weight: 600;
    color: $color-text-primary;
  }

  &__progress {
    margin-bottom: 12px;
  }

  &__counters {
    display: flex;
    gap: 24px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  &__counter {
    display: flex;
    align-items: baseline;
    gap: 6px;

    &-value {
      font-size: 18px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      color: $color-text-primary;
    }

    &-label {
      font-size: 12px;
      color: $color-text-secondary;
    }

    &--success &-value {
      color: $color-success;
    }

    &--danger &-value {
      color: $color-danger;
    }
  }

  &__active {
    background: $color-bg-page;
    border-radius: $radius-sm;
    padding: 8px 12px;
    margin-bottom: 12px;
    max-height: 120px;
    overflow-y: auto;
  }

  &__active-title {
    font-size: 12px;
    margin-bottom: 4px;
  }

  &__active-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    font-size: 12px;
    padding: 2px 0;
  }

  &__log-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
    font-size: 13px;
  }
}
</style>
