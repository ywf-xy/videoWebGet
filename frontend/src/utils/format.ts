/**
 * 格式化工具（ARCHITECTURE §11.3）：统一时间 / 字节 / 耗时 / 百分比格式，
 * 任何空值都必须返回 `--`，禁止出现 `NaN` / `undefined`（NFR-12）。
 */

const EMPTY = '--'

/** 安全取值：null/undefined/NaN/空串 → `--` */
export function safe(value: unknown): string {
  if (value === null || value === undefined || value === '') return EMPTY
  if (typeof value === 'number' && Number.isNaN(value)) return EMPTY
  return String(value)
}

/** 字节 → 人类可读（1.2 MB） */
export function formatBytes(bytes?: number | null, digits = 1): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return EMPTY
  const size = Number(bytes)
  if (size < 0) return EMPTY
  if (size === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)))
  const value = size / 1024 ** index
  return `${value.toFixed(index === 0 ? 0 : digits)} ${units[index]}`
}

/** 毫秒 → 耗时（1.2s / 3m20s / 1h05m） */
export function formatDuration(ms?: number | null): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return EMPTY
  const value = Math.max(0, Number(ms))
  if (value < 1000) return `${Math.round(value)}ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const restSeconds = Math.round(seconds % 60)
  if (minutes < 60) return `${minutes}m${String(restSeconds).padStart(2, '0')}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h${String(minutes % 60).padStart(2, '0')}m`
}

function parseDate(value?: string | null): Date | null {
  if (!value) return null
  const text = String(value).trim()
  if (!text) return null
  // 兼容后端 ISO 8601（含毫秒与时区偏移）与纯日期
  const normalized = text.includes('T') ? text : `${text}T00:00:00`
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** ISO → `YYYY-MM-DD HH:mm` */
export function formatDateTime(value?: string | null): string {
  const date = parseDate(value)
  if (!date) return EMPTY
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

/** ISO → `YYYY-MM-DD HH:mm:ss`（日志/详情用） */
export function formatDateTimeSeconds(value?: string | null): string {
  const date = parseDate(value)
  if (!date) return EMPTY
  return `${formatDateTime(value)}:${pad(date.getSeconds())}`
}

/** ISO → `YYYY-MM-DD` */
export function formatDate(value?: string | null): string {
  const date = parseDate(value)
  if (!date) return EMPTY
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** ISO → 相对时间（仅健康度「最近成功」使用） */
export function formatRelative(value?: string | null): string {
  const date = parseDate(value)
  if (!date) return EMPTY
  const diff = Date.now() - date.getTime()
  if (diff < 0) return '刚刚'
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  return formatDate(value)
}

/** 0-100 → `85%` */
export function formatPercent(value?: number | null, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY
  return `${Number(value).toFixed(digits)}%`
}

/** 数字千分位 */
export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY
  return Number(value).toLocaleString('zh-CN')
}

/** 0.8234 → `82.3%`（成功率等比率字段） */
export function formatRatio(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY
  return `${(Number(value) * 100).toFixed(digits)}%`
}

/** 截断长文本（用于单元格展示，配合 tooltip 显示全量） */
export function truncate(value?: string | null, max = 40): string {
  const text = safe(value)
  if (text === EMPTY) return text
  return text.length > max ? `${text.slice(0, max)}…` : text
}
