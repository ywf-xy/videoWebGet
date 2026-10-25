/**
 * 数据源 store（ARCHITECTURE §8.3）：列表 / 详情 / 健康度缓存 / 增删改 / 导入导出。
 * 300ms 防抖在组件侧完成，store 只负责「一次查询」。
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createDataSource,
  deleteDataSource,
  exportDataSources,
  fetchDataSource,
  fetchDataSourceHealth,
  fetchDataSources,
  importDataSources,
  toggleDataSource,
  updateDataSource,
} from '@/api/dataSource'
import type {
  DataSourceDetail,
  DataSourceItem,
  DataSourcePayload,
  DataSourceQuery,
  DataSourceUpdatePayload,
  ExportQuery,
  HealthResp,
  ImportResultResp,
} from '@/api/types'

const defaultQuery = (): DataSourceQuery => ({ page: 1, pageSize: 10 })

export const useDataSourceStore = defineStore('dataSource', () => {
  const list = ref<DataSourceItem[]>([])
  const total = ref(0)
  const query = ref<DataSourceQuery>(defaultQuery())
  const current = ref<DataSourceDetail | null>(null)
  const healthMap = ref<Record<number, HealthResp>>({})
  const loading = ref(false)
  const detailLoading = ref(false)
  const errorMessage = ref('')

  async function fetchList(next?: Partial<DataSourceQuery>): Promise<void> {
    if (next) query.value = { ...query.value, ...next }
    loading.value = true
    errorMessage.value = ''
    try {
      const data = await fetchDataSources(query.value)
      list.value = data.items
      total.value = data.total
      query.value = { ...query.value, page: data.page, pageSize: data.pageSize }
    } catch {
      list.value = []
      total.value = 0
      errorMessage.value = '数据源列表加载失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(id: number): Promise<DataSourceDetail | null> {
    detailLoading.value = true
    try {
      const data = await fetchDataSource(id)
      current.value = data
      return data
    } catch {
      current.value = null
      return null
    } finally {
      detailLoading.value = false
    }
  }

  async function fetchHealth(id: number): Promise<HealthResp | null> {
    try {
      const data = await fetchDataSourceHealth(id)
      healthMap.value = { ...healthMap.value, [id]: data }
      return data
    } catch {
      return null
    }
  }

  function save(id: number | null, payload: DataSourcePayload | DataSourceUpdatePayload): Promise<number> {
    return id === null
      ? createDataSource(payload as DataSourcePayload).then((res) => res.id)
      : updateDataSource(id, payload).then((res) => res.id)
  }

  async function toggle(id: number, enabled: boolean): Promise<boolean> {
    const data = await toggleDataSource(id, enabled)
    const target = list.value.find((item) => item.id === id)
    if (target) target.enabled = data.enabled
    if (current.value && current.value.id === id) current.value.enabled = data.enabled
    return data.enabled
  }

  async function remove(id: number): Promise<void> {
    await deleteDataSource(id)
    list.value = list.value.filter((item) => item.id !== id)
    total.value = Math.max(0, total.value - 1)
  }

  async function importFile(file: File, overwrite: boolean): Promise<ImportResultResp> {
    const result = await importDataSources(file, overwrite)
    await fetchList({ page: 1 })
    return result
  }

  function exportFile(params: ExportQuery): Promise<{ blob: Blob; filename: string }> {
    return exportDataSources(params)
  }

  function resetQuery(): void {
    query.value = defaultQuery()
  }

  /** 工作页切换备用地址后同步本地缓存（列表项不暴露 current_url，无需处理） */
  function patchCurrentUrl(id: number, url: string): void {
    if (current.value && current.value.id === id) current.value.current_url = url
  }

  return {
    list,
    total,
    query,
    current,
    healthMap,
    loading,
    detailLoading,
    errorMessage,
    fetchList,
    fetchDetail,
    fetchHealth,
    save,
    toggle,
    remove,
    importFile,
    exportFile,
    resetQuery,
    patchCurrentUrl,
  }
})
