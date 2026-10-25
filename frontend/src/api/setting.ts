/**
 * 设置接口（对应后端 `api/setting.py`）。
 */
import { get, post, put, upload } from './request'
import type {
  AvatarResp,
  PurgeLogsResp,
  RebuildStatsResp,
  SettingsPayload,
  SettingsUpdatePayload,
  TestPathResp,
} from './types'

/** 读取全量设置 */
export function fetchSettings(): Promise<SettingsPayload> {
  return get<SettingsPayload>('/settings')
}

/** 保存设置（部分字段；线程数越界 1001、目录不可写 5002） */
export function saveSettings(payload: SettingsUpdatePayload): Promise<SettingsPayload> {
  return put<SettingsPayload>('/settings', payload)
}

/** 上传头像（≤2MB，png/jpg） */
export function uploadAvatar(file: File): Promise<AvatarResp> {
  const form = new FormData()
  form.append('file', file)
  return upload<AvatarResp>('/settings/avatar', form)
}

/** 测试目录可写性（返回 errno 原因） */
export function testPath(path: string): Promise<TestPathResp> {
  return post<TestPathResp>('/settings/test-path', { path })
}

/** 清理历史任务日志 */
export function purgeLogs(keepDays = 7): Promise<PurgeLogsResp> {
  return post<PurgeLogsResp>('/settings/purge-logs', { keep_days: keepDays })
}

/** 重建统计缓存（健康度重算，危险区操作） */
export function rebuildStats(): Promise<RebuildStatsResp> {
  return post<RebuildStatsResp>('/settings/rebuild-stats')
}
