/**
 * 任务接口（对应后端 `api/task.py`）。
 */
import { get, post } from './request'
import type {
  PagePayload,
  SubmittedResp,
  TaskDetail,
  TaskItem,
  TaskLogItem,
  TaskQuery,
  TaskRetryResp,
} from './types'

/** 任务分页列表（状态/关键字过滤，按 seq_no 升序） */
export function fetchTasks(query: TaskQuery = {}): Promise<PagePayload<TaskItem>> {
  return get<PagePayload<TaskItem>>('/tasks', { ...query })
}

/** 任务详情 + 结果记录 */
export function fetchTaskDetail(taskId: number): Promise<TaskDetail> {
  return get<TaskDetail>(`/tasks/${taskId}`)
}

/** 任务日志（级别 / 关键字） */
export function fetchTaskLogs(
  taskId: number,
  query: { level?: string; keyword?: string; pageSize?: number } = {},
): Promise<TaskLogItem[]> {
  return get<TaskLogItem[]>(`/tasks/${taskId}/logs`, { ...query })
}

/** 单条重试（仅 failed，否则 3007） */
export function retryTask(taskId: number): Promise<TaskRetryResp> {
  return post<TaskRetryResp>(`/tasks/${taskId}/retry`)
}

/** 批量重试失败任务 */
export function retryTasks(taskIds: number[]): Promise<SubmittedResp> {
  return post<SubmittedResp>('/tasks/retry', { task_ids: taskIds })
}
