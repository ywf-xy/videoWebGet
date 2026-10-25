/**
 * 设置 store（ARCHITECTURE §8.3）：设置项 + 系统信息（含 ffmpeg 探测结果）。
 * 保存后刷新 systemInfo，保证「输出根目录 / ffmpeg 状态」立即反映。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { fetchSystemInfo } from '@/api/system'
import {
  fetchSettings,
  purgeLogs as apiPurgeLogs,
  rebuildStats as apiRebuildStats,
  saveSettings,
  testPath as apiTestPath,
  uploadAvatar as apiUploadAvatar,
} from '@/api/setting'
import type {
  SettingsPayload,
  SettingsUpdatePayload,
  SystemInfoResp,
  TestPathResp,
} from '@/api/types'

export const useSettingStore = defineStore('setting', () => {
  const settings = ref<SettingsPayload | null>(null)
  const systemInfo = ref<SystemInfoResp | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const systemLoading = ref(false)
  const errorMessage = ref('')

  /** ffmpeg 是否可用（视频相关页面据此显示红字提示） */
  const ffmpegAvailable = computed(() => systemInfo.value?.ffmpeg.available ?? null)

  async function load(): Promise<void> {
    loading.value = true
    errorMessage.value = ''
    try {
      settings.value = await fetchSettings()
    } catch {
      errorMessage.value = '设置加载失败'
    } finally {
      loading.value = false
    }
  }

  async function loadSystemInfo(): Promise<void> {
    systemLoading.value = true
    try {
      systemInfo.value = await fetchSystemInfo()
    } catch {
      systemInfo.value = null
    } finally {
      systemLoading.value = false
    }
  }

  async function save(payload: SettingsUpdatePayload): Promise<SettingsPayload> {
    saving.value = true
    try {
      const data = await saveSettings(payload)
      settings.value = data
      void loadSystemInfo()
      return data
    } finally {
      saving.value = false
    }
  }

  async function uploadAvatar(file: File): Promise<string> {
    const data = await apiUploadAvatar(file)
    if (settings.value) settings.value.profile.avatar = data.url
    return data.url
  }

  function testPath(path: string): Promise<TestPathResp> {
    return apiTestPath(path)
  }

  async function purgeLogs(keepDays: number): Promise<number> {
    const data = await apiPurgeLogs(keepDays)
    return data.deleted
  }

  async function rebuildStats(): Promise<number> {
    const data = await apiRebuildStats()
    return data.updated
  }

  /** 确保系统信息已加载（多个页面共用，避免重复请求） */
  async function ensureSystemInfo(): Promise<void> {
    if (systemInfo.value === null && !systemLoading.value) {
      await loadSystemInfo()
    }
  }

  return {
    settings,
    systemInfo,
    loading,
    saving,
    systemLoading,
    errorMessage,
    ffmpegAvailable,
    load,
    loadSystemInfo,
    ensureSystemInfo,
    save,
    uploadAvatar,
    testPath,
    purgeLogs,
    rebuildStats,
  }
})
