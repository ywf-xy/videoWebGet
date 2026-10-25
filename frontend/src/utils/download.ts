/**
 * 文件下载工具（ARCHITECTURE §8.4-⑤）：导出 / 模板接口返回 JSON 附件，
 * 需要从 `content-disposition` 解析文件名，并兼容后端未给中文文件名的情况。
 */

/** 从 content-disposition 解析文件名（支持 filename*=UTF-8'' 编码） */
export function parseFilename(disposition?: string | null, fallback = 'download.json'): string {
  if (!disposition) return fallback
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return fallback
    }
  }
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  return match ? match[1].trim() : fallback
}

/** 触发浏览器下载 Blob */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

/** 把普通对象导出为 UTF-8 JSON 文件（本地导出兜底） */
export function downloadJson(data: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  saveBlob(blob, filename)
}
