/**
 * 后端 DTO 类型定义（ARCHITECTURE §11.1 / §11.2）。
 *
 * 字段一律 snake_case，与 `backend/app/schemas/*.py` 严格一致；分页信封固定
 * `{ items, total, page, pageSize }`。修改后端 schema 时必须同步本文件。
 */

/* ------------------------------------------------------------------ *
 * 通用
 * ------------------------------------------------------------------ */
export interface ApiEnvelope<T> {
  code: number
  data: T | null
  message: string
}

export interface PagePayload<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface PageQuery {
  page?: number
  pageSize?: number
}

export type SourceType = 'video' | 'text' | 'image'
export type StrategyType = 'count' | 'page' | 'date'
export type ExportFormat = 'txt' | 'pdf'

/* ------------------------------------------------------------------ *
 * 首页统计（api/dashboard.py）
 * ------------------------------------------------------------------ */
export interface HealthSummary {
  healthy: number
  total: number
}

export interface RunningBatchItem {
  batch_id: number
  data_source_id: number
  data_source_name: string | null
  data_source_type: string | null
  strategy: string
  status: string
  phase: string
  progress: number
  total: number
  done: number
  failed: number
  skipped: number
  elapsed_ms: number
  created_at: string | null
}

export interface OverviewResp {
  health: HealthSummary
  today: number
  week: number
  month: number
  running: RunningBatchItem[]
}

export interface TrendPoint {
  label: string
  count: number
}

export type TrendGranularity = 'day' | 'week' | 'month'

export interface TrendResp {
  granularity: string
  points: TrendPoint[]
}

export interface HealthSourceItem {
  data_source_id: number
  name: string
  type: string
  health_score: number | null
  success_rate_20: number | null
  last_success_at: string | null
  level: string
}

/* ------------------------------------------------------------------ *
 * 数据源（api/data_source.py）
 * ------------------------------------------------------------------ */
export interface DataSourceItem {
  id: number
  name: string
  type: string
  category: string | null
  homepage_url: string
  alt_urls_count: number
  health_score: number | null
  last_crawled_at: string | null
  total_items: number
  enabled: boolean
  has_script: boolean
  created_at: string | null
  updated_at: string | null
}

export interface DataSourceDetail {
  id: number
  name: string
  type: string
  category: string | null
  homepage_url: string
  alt_urls: string[]
  current_url: string | null
  script: string | null
  script_entry: string
  config_json: Record<string, unknown>
  is_novel: boolean
  enabled: boolean
  health_score: number | null
  success_rate_20: number | null
  last_success_at: string | null
  last_crawled_at: string | null
  total_items: number
  cursor_last_item_no: number
  cursor_last_page: number
  cursor_last_success_date: string | null
  notes: string | null
  created_at: string | null
  updated_at: string | null
}

export interface DataSourcePayload {
  name: string
  type: SourceType
  category?: string | null
  homepage_url: string
  alt_urls?: string[]
  current_url?: string | null
  script?: string | null
  script_entry?: string
  config_json?: Record<string, unknown>
  is_novel?: boolean
  enabled?: boolean
  notes?: string | null
}

export type DataSourceUpdatePayload = Partial<DataSourcePayload>

export interface DataSourceQuery extends PageQuery {
  type?: string
  keyword?: string
  category?: string
  enabled?: boolean
}

export interface HealthResp {
  health_score: number | null
  success_rate_20: number | null
  last_success_at: string | null
  sample_size: number
}

export interface ScriptValidateResp {
  valid: boolean
  line: number | null
  column: number | null
  message: string
}

export interface ScriptTestResp {
  count: number
  fields: string[]
  samples: Record<string, unknown>[]
}

export interface ImportRowResult {
  line: number
  status: string
  reason: string
}

export interface ImportResultResp {
  success: number
  failed: number
  rows: ImportRowResult[]
}

export interface ExportQuery {
  scope: 'all' | 'selected' | 'type'
  ids?: number[]
  type?: string
}

/* ------------------------------------------------------------------ *
 * 批次（api/batch.py）
 * ------------------------------------------------------------------ */
export interface BatchCreatePayload {
  data_source_id: number
  strategy: StrategyType
  strategy_params: Record<string, unknown>
  export_format?: ExportFormat | null
}

export interface BatchCreatedResp {
  batch_id: number
  status: string
}

export interface BatchItem {
  id: number
  data_source_id: number
  data_source_name: string | null
  data_source_type: string | null
  strategy: string
  status: string
  phase: string
  total_tasks: number
  done_tasks: number
  failed_tasks: number
  skipped_tasks: number
  progress: number
  threads: number
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface BatchDetail extends Omit<BatchItem, 'id'> {
  id: number
  strategy_params: Record<string, unknown>
  export_format: string | null
  request_url: string | null
  cursor_before: Record<string, unknown> | null
  cursor_after: Record<string, unknown> | null
  error_code: string | null
  error_msg: string | null
  warnings: string[]
  pause_requested_at: string | null
  updated_at: string | null
}

export interface BatchProgressInfo {
  status: string
  phase: string
  progress: number
  total: number
  done: number
  failed: number
  skipped: number
  elapsed_ms: number
}

export interface ActiveTaskItem {
  task_id: number
  title: string
  step_done: number
  step_total: number
}

export interface BatchLogItem {
  id: number
  level: string
  message: string
  task_id: number | null
  created_at: string
}

export interface BatchProgressResp {
  batch: BatchProgressInfo
  active: ActiveTaskItem[]
  logs: BatchLogItem[] | null
  last_log_id: number
}

export interface BatchLogsResp {
  items: BatchLogItem[]
  last_id: number
}

export interface BatchStatusResp {
  status: string
}

export interface LatestBatchResp {
  has_history: boolean
  batch_id: number | null
  status: string | null
  strategy: string | null
  finished_at: string | null
  last_item_no: number
  last_page: number
  last_success_date: string | null
  last_item_title: string | null
  done_tasks: number
  failed_tasks: number
}

export interface BatchQuery extends PageQuery {
  data_source_id?: number
  status?: string
}

export interface BatchLogQuery {
  level?: string
  keyword?: string
  after_id?: number
  pageSize?: number
}

/* ------------------------------------------------------------------ *
 * 任务（api/task.py）
 * ------------------------------------------------------------------ */
export interface TaskItem {
  id: number
  batch_id: number
  data_source_id: number
  seq_no: number
  title: string
  source_url: string
  status: string
  attempt_count: number
  error_code: string | null
  error_msg: string | null
  step_done: number
  step_total: number
  duration_ms: number
  file_size: number
  file_count: number
  word_count: number
  image_count: number
  extra: Record<string, unknown>
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface TaskResultInfo {
  id: number
  artifact_type: string
  output_path: string
  file_size: number
  file_count: number
  fingerprint: string | null
  extra: Record<string, unknown>
  created_at: string | null
}

export interface TaskDetail {
  id: number
  batch_id: number
  data_source_id: number
  seq_no: number
  title: string
  source_url: string
  payload: Record<string, unknown>
  status: string
  attempt_count: number
  error_code: string | null
  error_msg: string | null
  step_done: number
  step_total: number
  duration_ms: number
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  result: TaskResultInfo | null
}

export interface TaskLogItem {
  id: number
  level: string
  message: string
  created_at: string
  task_id: number | null
}

export interface TaskRetryResp {
  status: string
  attempt_count: number
}

export interface SubmittedResp {
  submitted: number
}

export interface TaskQuery extends PageQuery {
  batch_id?: number
  status?: string
  keyword?: string
}

/* ------------------------------------------------------------------ *
 * 产物（api/artifact.py）
 * ------------------------------------------------------------------ */
export interface ArtifactItem {
  id: number
  task_id: number
  data_source_id: number
  data_source_name: string
  type: string
  name: string
  category: string | null
  path: string
  size: number
  status: string
  is_file_exists: boolean
  created_at: string | null
}

export interface ArtifactDetail extends ArtifactItem {
  task_result_id: number | null
  error_msg: string | null
  updated_at: string | null
}

export interface ArtifactQuery extends PageQuery {
  data_source_id?: number
  type?: string
  name?: string
  date_from?: string
  date_to?: string
  status?: string
}

export interface OpenDirResp {
  opened: boolean
  path: string
}

export interface RedownloadResp {
  task_id: number
  status: string
}

/* ------------------------------------------------------------------ *
 * 设置 / 系统（api/setting.py、api/system.py）
 * ------------------------------------------------------------------ */
export interface ProfilePayload {
  nickname: string
  avatar: string
  email: string
}

export interface RetryPayload {
  max_attempts: number
  base_interval: number
}

export interface HealthSettingPayload {
  refresh_interval: number
}

export interface SettingsPayload {
  profile: ProfilePayload
  output_root: string
  max_threads: number
  retry: RetryPayload
  health: HealthSettingPayload
}

export interface SettingsUpdatePayload {
  profile?: ProfilePayload
  output_root?: string
  max_threads?: number
  retry?: RetryPayload
  health?: HealthSettingPayload
}

export interface AvatarResp {
  url: string
}

export interface TestPathResp {
  writable: boolean
  errno: number | null
  reason: string | null
}

export interface PurgeLogsResp {
  deleted: number
}

export interface RebuildStatsResp {
  updated: number
}

export interface FfmpegInfo {
  available: boolean
  version: string | null
  path: string | null
}

export interface ThreadInfo {
  active: number
  max: number
}

export interface SystemInfoResp {
  version: string
  python: string
  db_path: string
  db_size: number
  output_root: string
  ffmpeg: FfmpegInfo
  threads: ThreadInfo
}

export interface MemoryInfo {
  used: number
  total: number
  percent: number
}

export interface MetricsResp {
  cpu_percent: number
  memory: MemoryInfo
  threads: ThreadInfo
  uptime_s: number
}

export interface HealthCheckResp {
  status: string
  version: string
}
