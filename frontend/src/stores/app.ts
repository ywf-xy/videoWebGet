/**
 * 全局应用 store（ARCHITECTURE §8.3）：线程占用、系统指标、侧栏折叠、自动刷新开关。
 * 3s 轮询 `/system/metrics`，供 MainLayout 与首页共用；可关闭，且页面隐藏时自动暂停。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { backendOnline } from '@/api/request'
import { fetchMetrics } from '@/api/system'
import type { MemoryInfo, ThreadInfo } from '@/api/types'

const METRICS_INTERVAL = 3000

function readBool(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(key)
    return raw === null ? fallback : raw === '1'
  } catch {
    return fallback
  }
}

function writeBool(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // 隐私模式下忽略
  }
}

export const useAppStore = defineStore('app', () => {
  const threads = ref<ThreadInfo>({ active: 0, max: 0 })
  const cpuPercent = ref(0)
  const memory = ref<MemoryInfo>({ used: 0, total: 0, percent: 0 })
  const uptimeSeconds = ref(0)
  const metricsLoading = ref(false)
  const metricsError = ref(false)
  const autoRefresh = ref(readBool('crawlerhub.autoRefresh', true))
  const sidebarCollapsed = ref(readBool('crawlerhub.sidebarCollapsed', false))
  const online = backendOnline

  let timer: number | null = null

  /** 右上角「活跃/最大」线程文案 */
  const threadText = computed(() => {
    const max = threads.value.max || 0
    return max > 0 ? `${threads.value.active}/${max}` : '--'
  })

  /** 线程占用百分比（0-100） */
  const threadPercent = computed(() => {
    const max = threads.value.max || 0
    if (max <= 0) return 0
    return Math.min(100, Math.round((threads.value.active / max) * 100))
  })

  async function fetchOnce(): Promise<void> {
    metricsLoading.value = true
    try {
      const data = await fetchMetrics()
      cpuPercent.value = data.cpu_percent
      memory.value = data.memory
      threads.value = data.threads
      uptimeSeconds.value = data.uptime_s
      metricsError.value = false
    } catch {
      // 具体错误已由 request 层 toast；这里只标记卡片降级
      metricsError.value = true
      threads.value = { active: 0, max: threads.value.max }
    } finally {
      metricsLoading.value = false
    }
  }

  function stopPolling(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function startPolling(): void {
    stopPolling()
    if (!autoRefresh.value) return
    if (typeof document !== 'undefined' && document.hidden) return
    void fetchOnce()
    timer = window.setInterval(() => {
      if (!autoRefresh.value) return
      if (typeof document !== 'undefined' && document.hidden) return
      void fetchOnce()
    }, METRICS_INTERVAL)
  }

  function setAutoRefresh(value: boolean): void {
    autoRefresh.value = value
    writeBool('crawlerhub.autoRefresh', value)
    if (value) {
      startPolling()
    } else {
      stopPolling()
    }
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    writeBool('crawlerhub.sidebarCollapsed', sidebarCollapsed.value)
  }

  /** 页面隐藏时暂停，恢复时立即拉一次（省电、避免后台空转） */
  function handleVisibility(): void {
    if (document.hidden) {
      stopPolling()
    } else if (autoRefresh.value) {
      startPolling()
    }
  }

  return {
    threads,
    threadText,
    threadPercent,
    cpuPercent,
    memory,
    uptimeSeconds,
    metricsLoading,
    metricsError,
    autoRefresh,
    sidebarCollapsed,
    online,
    fetchOnce,
    startPolling,
    stopPolling,
    setAutoRefresh,
    toggleSidebar,
    handleVisibility,
  }
})
