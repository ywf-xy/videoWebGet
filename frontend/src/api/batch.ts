/**
 * 批次接口（对应后端 `api/batch.py`）。
 * 进度轮询的唯一入口在 `stores/batch.ts`，本文件只做纯请求。
 */
import { get, post } from './request'
import type {
  BatchCreatePayload,
  BatchCreatedResp,
  BatchDetail,
  BatchItem,
  BatchLogQuery,
  BatchLogsResp,
  BatchProgressResp,
  BatchQuery,
  BatchStatusResp,
  LatestBatchResp,
  PagePayload,
  SubmittedResp,
} from './types'

/** 创建批次并立即开始采集（单飞冲突 3001 / 队列超限 3002 / ffmpeg 缺失 3003） */
export function createBatch(payload: BatchCreatePayload): Promise<BatchCreatedResp> {
  return post<BatchCreatedResp>('/batches', payload)
}

/** 批次分页列表 */
export function fetchBatches(query: BatchQuery = {}): Promise<PagePayload<BatchItem>> {
  return get<PagePayload<BatchItem>>('/batches', { ...query })
}

/** 批次详情（含游标前后、warnings） */
export function fetchBatchDetail(batchId: number): Promise<BatchDetail> {
  return get<BatchDetail>(`/batches/${batchId}`)
}

/** 进度轮询：afterLogId 传上次的 last_log_id 以增量拉日志 */
export function fetchBatchProgress(
  batchId: number,
  afterLogId?: number | null,
): Promise<BatchProgressResp> {
  return get<BatchProgressResp>(`/batches/${batchId}/progress`, {
    after_log_id: afterLogId ?? undefined,
  })
}

/** 暂停（不杀线程，任务在原子步骤后回退 pending） */
export function pauseBatch(batchId: number): Promise<BatchStatusResp> {
  return post<BatchStatusResp>(`/batches/${batchId}/pause`)
}

/** 恢复 */
export function resumeBatch(batchId: number): Promise<BatchStatusResp> {
  return post<BatchStatusResp>(`/batches/${batchId}/resume`)
}

/** 重试全部失败任务（无可重试 → 3006） */
export function retryFailedTasks(batchId: number): Promise<SubmittedResp> {
  return post<SubmittedResp>(`/batches/${batchId}/retry-failed`)
}

/** 批次日志（级别 / 关键字 / 增量） */
export function fetchBatchLogs(batchId: number, query: BatchLogQuery = {}): Promise<BatchLogsResp> {
  return get<BatchLogsResp>(`/batches/${batchId}/logs`, { ...query })
}

/** 工作页「上次采集到」摘要（无历史 has_history=false） */
export function fetchLatestBatch(dataSourceId: number): Promise<LatestBatchResp> {
  return get<LatestBatchResp>('/batches/latest', { data_source_id: dataSourceId })
}
