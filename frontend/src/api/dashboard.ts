/**
 * 首页统计接口（对应后端 `api/dashboard.py`）。
 */
import { get } from './request'
import type { HealthSourceItem, OverviewResp, TrendGranularity, TrendResp } from './types'

/** 首页概览：健康源数/总数 + 今日/本周/本月 + 运行中批次（单请求聚合） */
export function fetchOverview(): Promise<OverviewResp> {
  return get<OverviewResp>('/dashboard/overview')
}

/** 采集量趋势：day=按小时、week/month=按天 */
export function fetchTrend(granularity: TrendGranularity = 'day'): Promise<TrendResp> {
  return get<TrendResp>('/dashboard/trend', { granularity })
}

/** 数据源健康度列表（order: asc | desc，无记录 health_score 为 null） */
export function fetchHealthList(order: 'asc' | 'desc' = 'asc'): Promise<HealthSourceItem[]> {
  return get<HealthSourceItem[]>('/dashboard/health', { order })
}
