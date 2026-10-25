/**
 * 产物 store（ARCHITECTURE §8.3）：分页与筛选状态同源，避免组件各自维护页码。
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import {
  deleteArtifact,
  fetchArtifacts,
  openArtifactDir,
  redownloadArtifact,
} from '@/api/artifact'
import type { ArtifactItem, ArtifactQuery, OpenDirResp, RedownloadResp } from '@/api/types'

const defaultFilters = (): ArtifactQuery => ({ page: 1, pageSize: 10 })

export const useArtifactStore = defineStore('artifact', () => {
  const list = ref<ArtifactItem[]>([])
  const total = ref(0)
  const filters = ref<ArtifactQuery>(defaultFilters())
  const loading = ref(false)
  const errorMessage = ref('')

  async function fetchList(next?: Partial<ArtifactQuery>): Promise<void> {
    if (next) filters.value = { ...filters.value, ...next }
    loading.value = true
    errorMessage.value = ''
    try {
      const data = await fetchArtifacts(filters.value)
      list.value = data.items
      total.value = data.total
      filters.value = { ...filters.value, page: data.page, pageSize: data.pageSize }
    } catch {
      list.value = []
      total.value = 0
      errorMessage.value = '产物列表加载失败'
    } finally {
      loading.value = false
    }
  }

  /** 条件变化时回到第 1 页 */
  async function applyFilters(next: ArtifactQuery): Promise<void> {
    filters.value = { ...next, page: 1 }
    await fetchList()
  }

  function resetFilters(): void {
    filters.value = defaultFilters()
  }

  async function remove(id: number, deleteFile = true): Promise<void> {
    await deleteArtifact(id, deleteFile)
    await fetchList()
  }

  function redownload(id: number): Promise<RedownloadResp> {
    return redownloadArtifact(id)
  }

  function openDir(id: number): Promise<OpenDirResp> {
    return openArtifactDir(id)
  }

  return {
    list,
    total,
    filters,
    loading,
    errorMessage,
    fetchList,
    applyFilters,
    resetFilters,
    remove,
    redownload,
    openDir,
  }
})
