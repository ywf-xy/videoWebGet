/**
 * 产物接口（对应后端 `api/artifact.py`）。
 */
import { del, get, post } from './request'
import type {
  ArtifactDetail,
  ArtifactItem,
  ArtifactQuery,
  OpenDirResp,
  PagePayload,
  RedownloadResp,
} from './types'

/** 5 条件组合筛选 + 分页（含 is_file_exists 判定） */
export function fetchArtifacts(query: ArtifactQuery = {}): Promise<PagePayload<ArtifactItem>> {
  return get<PagePayload<ArtifactItem>>('/artifacts', { ...query })
}

/** 产物详情（含失败原因） */
export function fetchArtifactDetail(id: number): Promise<ArtifactDetail> {
  return get<ArtifactDetail>(`/artifacts/${id}`)
}

/** 打开所在目录（失败时降级返回 path） */
export function openArtifactDir(id: number): Promise<OpenDirResp> {
  return post<OpenDirResp>(`/artifacts/${id}/open-dir`)
}

/** 重新下载（仅失败产物，否则 3007） */
export function redownloadArtifact(id: number): Promise<RedownloadResp> {
  return post<RedownloadResp>(`/artifacts/${id}/redownload`)
}

/** 删除产物（可选同时删除磁盘文件） */
export function deleteArtifact(id: number, deleteFile = true): Promise<{ deleted: number }> {
  return del<{ deleted: number }>(`/artifacts/${id}`, { delete_file: deleteFile })
}
