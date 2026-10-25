/**
 * 系统接口（对应后端 `api/system.py`）。
 */
import { get } from './request'
import type { HealthCheckResp, MetricsResp, SystemInfoResp } from './types'

/** 系统信息（版本 / Python / DB / 输出根目录 / ffmpeg / 线程占用） */
export function fetchSystemInfo(): Promise<SystemInfoResp> {
  return get<SystemInfoResp>('/system/info')
}

/** 运行指标（CPU / 内存 / 线程 / uptime），3s 轮询 */
export function fetchMetrics(): Promise<MetricsResp> {
  return get<MetricsResp>('/system/metrics')
}

/** 健康检查（探活用） */
export function fetchHealthCheck(): Promise<HealthCheckResp> {
  return get<HealthCheckResp>('/health')
}
