/**
 * axios 统一封装（ARCHITECTURE §8.4）。
 *
 * 1) baseURL = `/api`（dev 由 vite proxy 转发到 127.0.0.1:8000）
 * 2) 响应拦截：`code === 0` → 直接返回 `data`；否则 toast `[code] message` 并 reject `BizError`
 * 3) 网络不可达 → 只提示一次「服务连接失败，请确认后端已启动」，并每 5s 探活
 * 4) 文件下载（导出/模板）走 `responseType: 'blob'`，从 content-disposition 取文件名
 * 5) 超时 15s，**不做自动重试**（避免与 2s 进度轮询叠加放大请求量）
 */
import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { parseFilename } from '@/utils/download'

import type { ApiEnvelope } from './types'

/** 后端可达性（MainLayout 用它显示顶部红条） */
export const backendOnline = ref(true)

/** 业务异常：携带后端错误码，便于调用方做定向处理（如 3003 → 引导装 ffmpeg） */
export class BizError extends Error {
  readonly code: number

  constructor(code: number, message: string) {
    super(message)
    this.name = 'BizError'
    this.code = code
  }
}

const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

/* ------------------------------------------------------------------ *
 * 提示节流：轮询期间同一错误只提示一次
 * ------------------------------------------------------------------ */
let lastToast = { message: '', at: 0 }

function toastError(message: string): void {
  const now = Date.now()
  if (message === lastToast.message && now - lastToast.at < 3000) return
  lastToast = { message, at: now }
  ElMessage({ type: 'error', message, duration: 4000, showClose: true })
}

function toastBizError(code: number, message: string): void {
  toastError(`[${code}] ${message}`)
}

/* ------------------------------------------------------------------ *
 * 后端可达性探活
 * ------------------------------------------------------------------ */
let probeTimer: number | null = null
let probing = false

function markOnline(): void {
  if (!backendOnline.value) {
    backendOnline.value = true
    ElMessage({ type: 'success', message: '后端服务已恢复连接', duration: 2000 })
  }
  backendOnline.value = true
  if (probeTimer !== null) {
    window.clearInterval(probeTimer)
    probeTimer = null
  }
}

async function probeOnce(): Promise<void> {
  if (probing) return
  probing = true
  try {
    await axios.get('/api/health', { timeout: 4000 })
    markOnline()
  } catch {
    // 仍然不可达：保持离线段位，等待下一轮
  } finally {
    probing = false
  }
}

function startProbe(): void {
  if (probeTimer !== null) return
  probeTimer = window.setInterval(() => {
    void probeOnce()
  }, 5000)
}

/* ------------------------------------------------------------------ *
 * 拦截器
 * ------------------------------------------------------------------ */
http.interceptors.response.use(
  (response: AxiosResponse) => {
    markOnline()
    // 文件下载：保留完整 response 以便读取 content-disposition
    if (response.config.responseType === 'blob') return response

    const body = response.data as ApiEnvelope<unknown> | null
    if (body && typeof body === 'object' && typeof body.code === 'number') {
      if (body.code === 0) return body.data as unknown as AxiosResponse
      toastBizError(body.code, body.message || '请求失败')
      return Promise.reject(new BizError(body.code, body.message || '请求失败'))
    }
    // 非标准响应（如后端直出 JSON 数组的附件接口）原样返回
    return response.data as unknown as AxiosResponse
  },
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    if (axios.isCancel(error)) return Promise.reject(error)

    const payload = error.response?.data
    if (payload && typeof payload === 'object' && typeof payload.code === 'number') {
      toastBizError(payload.code, payload.message || '请求失败')
      return Promise.reject(new BizError(payload.code, payload.message || '请求失败'))
    }

    if (!error.response) {
      backendOnline.value = false
      toastError('服务连接失败，请确认后端已启动')
      startProbe()
      return Promise.reject(new BizError(-1, '服务连接失败，请确认后端已启动'))
    }

    const status = error.response.status
    const message =
      status >= 500
        ? `服务异常（HTTP ${status}），请查看后端日志 logs/app.log`
        : `请求失败（HTTP ${status}）`
    toastError(message)
    return Promise.reject(new BizError(status >= 500 ? 5000 : 1001, message))
  },
)

/* ------------------------------------------------------------------ *
 * 便捷方法
 * ------------------------------------------------------------------ */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const data = await http.request(config)
  return data as unknown as T
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>({ url, method: 'get', params })
}

export function post<T>(url: string, data?: unknown): Promise<T> {
  return request<T>({ url, method: 'post', data })
}

export function put<T>(url: string, data?: unknown): Promise<T> {
  return request<T>({ url, method: 'put', data })
}

export function patch<T>(url: string, data?: unknown): Promise<T> {
  return request<T>({ url, method: 'patch', data })
}

export function del<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>({ url, method: 'delete', params })
}

/** 上传文件（multipart/form-data，Content-Type 由浏览器自动带 boundary） */
export function upload<T>(url: string, form: FormData): Promise<T> {
  return request<T>({
    url,
    method: 'post',
    data: form,
    // 导入/头像可能有 10MB 级文件，放宽超时
    timeout: 60000,
  })
}

export interface BlobResult {
  blob: Blob
  filename: string
}

/** 下载附件（导出/模板），返回 Blob 与后端给出的文件名 */
export async function requestBlob(
  config: AxiosRequestConfig,
  fallbackName = 'download.json',
): Promise<BlobResult> {
  const response = (await http.request({
    ...config,
    responseType: 'blob',
    timeout: 60000,
  })) as unknown as AxiosResponse<Blob>
  const disposition =
    (response.headers?.['content-disposition'] as string | undefined) ??
    (response.headers?.['Content-Disposition'] as string | undefined)
  return { blob: response.data, filename: parseFilename(disposition, fallbackName) }
}

export default http
