/**
 * 批次 store（ARCHITECTURE §8.3 / §8.5）—— 进度轮询的**唯一入口**。
 *
 * 规则：
 * - `startPolling(id)` 立即拉一次，然后 2s 一次；同一时刻只允许一个 timer；
 * - 终态（success / success_with_warning / failed）→ 停止轮询 + 结果通知；
 * - `paused` / `paused_with_warning` → 停止轮询（改为按钮手动刷新）；
 * - 携带 `after_log_id` 增量拉日志，本地最多保留 500 条；
 * - `document.hidden` 时暂停，恢复可见后立即补拉一次；
 * - 组件卸载 / 路由离开必须 `stopPolling()`。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'

import {
  createBatch,
  fetchBatchDetail,
  fetchBatchLogs,
  fetchBatchProgress,
  pauseBatch,
  resumeBatch,
  retryFailedTasks,
} from '@/api/batch'
import { fetchTaskLogs } from '@/api/task'
import { TERMINAL_BATCH_STATUSES } from '@/utils/constants'
import type {
  ActiveTaskItem,
  BatchCreatePayload,
  BatchCreatedResp,
  BatchDetail,
  BatchLogItem,
  BatchProgressInfo,
  TaskLogItem,
} from '@/api/types'

const POLL_INTERVAL = 2000
const MAX_LOGS = 500

export const useBatchStore = defineStore('batch', () => {
  const current = ref<BatchDetail | null>(null)
  const progress = ref<BatchProgressInfo | null>(null)
  const activeTasks = ref<ActiveTaskItem[]>([])
  const logs = ref<BatchLogItem[]>([])
  const lastLogId = ref(0)
  const batchId = ref<number | null>(null)
  const polling = ref(false)
  const busy = ref(false)
  const loadError = ref('')
  /** 每完成一次轮询自增，供任务表按需刷新 */
  const pollTick = ref(0)

  // 任务日志（TaskLogDrawer）
  const taskLogs = ref<TaskLogItem[]>([])
  const taskLogsLoading = ref(false)

  let timer: number | null = null
  let inFlight = false

  const status = computed(() => progress.value?.status ?? current.value?.status ?? '')
  const isTerminal = computed(() => TERMINAL_BATCH_STATUSES.includes(status.value))
  const isRunning = computed(() => status.value === 'running' || status.value === 'pending')
  const isPaused = computed(
    () => status.value === 'paused' || status.value === 'paused_with_warning',
  )
  const canPause = computed(() => isRunning.value)
  const canResume = computed(() => isPaused.value)
  const canRetryFailed = computed(
    () => isTerminal.value && (progress.value?.failed ?? 0) > 0,
  )
  const progressPercent = computed(() => progress.value?.progress ?? 0)

  function reset(): void {
    stopPolling()
    current.value = null
    progress.value = null
    activeTasks.value = []
    logs.value = []
    lastLogId.value = 0
    batchId.value = null
    loadError.value = ''
    taskLogs.value = []
    pollTick.value = 0
  }

  function appendLogs(items: BatchLogItem[] | null): void {
    if (!items || items.length === 0) return
    logs.value = [...logs.value, ...items].slice(-MAX_LOGS)
    lastLogId.value = items[items.length - 1].id
  }

  async function create(payload: BatchCreatePayload): Promise<BatchCreatedResp> {
    busy.value = true
    try {
      const created = await createBatch(payload)
      batchId.value = created.batch_id
      return created
    } finally {
      busy.value = false
    }
  }

  /** 拉取批次历史日志（进度接口在无 after_log_id 时返回 null，用于首屏/刷新后回填） */
  async function loadHistoryLogs(id: number): Promise<void> {
    try {
      const data = await fetchBatchLogs(id, { pageSize: 200 })
      logs.value = data.items.slice(-MAX_LOGS)
      lastLogId.value = data.last_id || (data.items.length ? data.items[data.items.length - 1].id : 0)
    } catch {
      // 忽略：日志不是关键路径
    }
  }

  async function loadDetail(id: number): Promise<void> {
    try {
      current.value = await fetchBatchDetail(id)
      loadError.value = ''
    } catch {
      loadError.value = '批次详情加载失败'
    }
  }

  /** 单次轮询（silent=true 时不显示 loading，不弹通知） */
  async function refreshOnce(silent = true): Promise<void> {
    const id = batchId.value
    if (id === null || inFlight) return
    inFlight = true
    try {
      const data = await fetchBatchProgress(id, lastLogId.value || undefined)
      progress.value = data.batch
      activeTasks.value = data.active
      if (data.logs === null && logs.value.length === 0) {
        // 首屏 / 刷新页面：进度接口不带增量日志，主动补拉一次历史
        await loadHistoryLogs(id)
      } else {
        appendLogs(data.logs)
      }
      pollTick.value += 1
      loadError.value = ''
      if (!silent) void loadDetail(id)

      if (TERMINAL_BATCH_STATUSES.includes(data.batch.status)) {
        stopPolling()
        await loadDetail(id)
        ElNotification({
          title: '采集完成',
          type: data.batch.status === 'failed' ? 'error' : 'success',
          message: `成功 ${data.batch.done} / 失败 ${data.batch.failed} / 跳过 ${data.batch.skipped}`,
          duration: 5000,
        })
      } else if (
        data.batch.status === 'paused' ||
        data.batch.status === 'paused_with_warning'
      ) {
        stopPolling()
        await loadDetail(id)
      }
    } catch {
      // 错误已由 request 层提示；保持轮询以便后端恢复后自动续上
    } finally {
      inFlight = false
    }
  }

  function startPolling(id: number): void {
    stopPolling()
    batchId.value = id
    polling.value = true
    void loadDetail(id)
    void refreshOnce(false)
    timer = window.setInterval(() => {
      if (document.hidden) return
      void refreshOnce(true)
    }, POLL_INTERVAL)
  }

  function stopPolling(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
    polling.value = false
  }

  function handleVisibility(): void {
    if (document.hidden) {
      if (timer !== null) {
        window.clearInterval(timer)
        timer = null
      }
    } else if (polling.value && timer === null) {
      void refreshOnce(true)
      timer = window.setInterval(() => {
        if (document.hidden) return
        void refreshOnce(true)
      }, POLL_INTERVAL)
    }
  }

  async function pause(): Promise<void> {
    const id = batchId.value
    if (id === null) return
    busy.value = true
    try {
      await pauseBatch(id)
      await refreshOnce(false)
    } finally {
      busy.value = false
    }
  }

  async function resume(): Promise<void> {
    const id = batchId.value
    if (id === null) return
    busy.value = true
    try {
      await resumeBatch(id)
      startPolling(id)
    } finally {
      busy.value = false
    }
  }

  async function retryFailed(): Promise<number> {
    const id = batchId.value
    if (id === null) return 0
    busy.value = true
    try {
      const data = await retryFailedTasks(id)
      startPolling(id)
      return data.submitted
    } finally {
      busy.value = false
    }
  }

  async function loadTaskLogs(
    taskId: number,
    options: { level?: string; keyword?: string } = {},
  ): Promise<void> {
    taskLogsLoading.value = true
    try {
      taskLogs.value = await fetchTaskLogs(taskId, {
        level: options.level === 'ALL' ? undefined : options.level,
        keyword: options.keyword || undefined,
        pageSize: 500,
      })
    } catch {
      taskLogs.value = []
    } finally {
      taskLogsLoading.value = false
    }
  }

  return {
    current,
    progress,
    activeTasks,
    logs,
    lastLogId,
    batchId,
    polling,
    busy,
    loadError,
    pollTick,
    taskLogs,
    taskLogsLoading,
    status,
    isTerminal,
    isRunning,
    isPaused,
    canPause,
    canResume,
    canRetryFailed,
    progressPercent,
    reset,
    create,
    loadDetail,
    loadHistoryLogs,
    refreshOnce,
    startPolling,
    stopPolling,
    handleVisibility,
    pause,
    resume,
    retryFailed,
    loadTaskLogs,
  }
})
