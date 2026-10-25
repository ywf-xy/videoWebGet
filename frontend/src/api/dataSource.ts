/**
 * 数据源接口（对应后端 `api/data_source.py`）。
 */
import { del, get, patch, post, put, requestBlob, upload } from './request'
import type {
  DataSourceDetail,
  DataSourceItem,
  DataSourcePayload,
  DataSourceQuery,
  DataSourceUpdatePayload,
  ExportQuery,
  HealthResp,
  ImportResultResp,
  PagePayload,
  ScriptTestResp,
  ScriptValidateResp,
} from './types'

/** 分页查询数据源（keyword 命中名称或地址） */
export function fetchDataSources(query: DataSourceQuery = {}): Promise<PagePayload<DataSourceItem>> {
  return get<PagePayload<DataSourceItem>>('/data-sources', { ...query })
}

/** 数据源详情（含脚本、config_json、游标三字段） */
export function fetchDataSource(id: number): Promise<DataSourceDetail> {
  return get<DataSourceDetail>(`/data-sources/${id}`)
}

/** 新增数据源，返回 id（name + homepage_url 冲突 → 2002） */
export function createDataSource(payload: DataSourcePayload): Promise<{ id: number }> {
  return post<{ id: number }>('/data-sources', payload)
}

/** 编辑数据源（仅提交字段生效） */
export function updateDataSource(
  id: number,
  payload: DataSourceUpdatePayload,
): Promise<{ id: number }> {
  return put<{ id: number }>(`/data-sources/${id}`, payload)
}

/** 启用 / 停用 */
export function toggleDataSource(id: number, enabled: boolean): Promise<{ enabled: boolean }> {
  return patch<{ enabled: boolean }>(`/data-sources/${id}/enabled`, { enabled })
}

/** 软删除（存在运行中批次 → 2003） */
export function deleteDataSource(id: number): Promise<{ deleted: number }> {
  return del<{ deleted: number }>(`/data-sources/${id}`)
}

/** 数据源健康度明细 */
export function fetchDataSourceHealth(id: number): Promise<HealthResp> {
  return get<HealthResp>(`/data-sources/${id}/health`)
}

/** 脚本语法校验（返回行号/列号） */
export function validateScript(
  id: number,
  script: string,
  entry = 'parse',
): Promise<ScriptValidateResp> {
  return post<ScriptValidateResp>(`/data-sources/${id}/script/validate`, { script, entry })
}

/** 脚本试运行（回显前 5 条） */
export function testScript(
  id: number,
  script: string,
  url: string,
  entry = 'parse',
): Promise<ScriptTestResp> {
  return post<ScriptTestResp>(`/data-sources/${id}/script/test`, { script, entry, url })
}

/** 导入 JSON / CSV（overwrite=true 覆盖同名） */
export function importDataSources(file: File, overwrite = false): Promise<ImportResultResp> {
  const form = new FormData()
  form.append('file', file)
  form.append('overwrite', String(overwrite))
  return upload<ImportResultResp>('/data-sources/import', form)
}

/** 导出数据源（JSON 附件） */
export function exportDataSources(query: ExportQuery): Promise<{ blob: Blob; filename: string }> {
  return requestBlob(
    {
      url: '/data-sources/export',
      method: 'get',
      params: {
        scope: query.scope,
        ids: query.ids?.length ? query.ids.join(',') : undefined,
        type: query.type,
      },
    },
    'crawlerhub-data-sources.json',
  )
}

/** 下载导入模板（JSON 附件） */
export function downloadTemplate(): Promise<{ blob: Blob; filename: string }> {
  return requestBlob(
    { url: '/data-sources/template', method: 'get' },
    'crawlerhub-data-source-template.json',
  )
}
