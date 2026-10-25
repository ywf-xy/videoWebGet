/**
 * 首页看板 store（ARCHITECTURE §8.3）。
 * `loadAll()` 用 `Promise.allSettled` 并行拉取，单卡失败置 null → 页面显示「--」而不白屏。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { fetchHealthList, fetchOverview, fetchTrend } from '@/api/dashboard'
import type { HealthSourceItem, OverviewResp, TrendGranularity, TrendResp } from '@/api/types'

export const useDashboardStore = defineStore('dashboard', () => {
  const overview = ref<OverviewResp | null>(null)
  const trend = ref<TrendResp | null>(null)
  const healthList = ref<HealthSourceItem[]>([])
  const granularity = ref<TrendGranularity>('day')
  const loading = ref(false)
  const trendLoading = ref(false)
  const healthLoading = ref(false)
  const overviewError = ref(false)
  const trendError = ref(false)
  const healthError = ref(false)
  const healthOrder = ref<'asc' | 'desc'>('asc')

  const isEmpty = computed(() => (overview.value?.health.total ?? 0) === 0)

  async function loadOverview(): Promise<void> {
    try {
      overview.value = await fetchOverview()
      overviewError.value = false
    } catch {
      overview.value = null
      overviewError.value = true
    }
  }

  async function loadTrend(next?: TrendGranularity): Promise<void> {
    if (next) granularity.value = next
    trendLoading.value = true
    try {
      trend.value = await fetchTrend(granularity.value)
      trendError.value = false
    } catch {
      trend.value = null
      trendError.value = true
    } finally {
      trendLoading.value = false
    }
  }

  async function loadHealth(next?: 'asc' | 'desc'): Promise<void> {
    if (next) healthOrder.value = next
    healthLoading.value = true
    try {
      healthList.value = await fetchHealthList(healthOrder.value)
      healthError.value = false
    } catch {
      healthList.value = []
      healthError.value = true
    } finally {
      healthLoading.value = false
    }
  }

  /** 并行加载全部数据；任一失败不影响其他卡片 */
  async function loadAll(): Promise<void> {
    loading.value = true
    try {
      await Promise.allSettled([loadOverview(), loadTrend(), loadHealth()])
    } finally {
      loading.value = false
    }
  }

  return {
    overview,
    trend,
    healthList,
    granularity,
    loading,
    trendLoading,
    healthLoading,
    overviewError,
    trendError,
    healthError,
    healthOrder,
    isEmpty,
    loadOverview,
    loadTrend,
    loadHealth,
    loadAll,
  }
})
