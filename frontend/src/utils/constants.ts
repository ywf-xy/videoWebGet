/**
 * 全站唯一的状态映射 / 枚举字面量来源（ARCHITECTURE §11.5、§11.6、NFR-10）。
 *
 * ⚠️ 同步源：后端 `backend/app/config.py::class E`、`backend/app/common/errors.py::class ErrCode`。
 * 后端新增枚举值时，此处必须同步，禁止在组件里硬编码文案或颜色。
 */

export type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export interface StatusMeta {
  label: string
  type: TagType
  plain?: boolean
}

/** 任务状态（6 种） */
export const TASK_STATUS_MAP: Record<string, StatusMeta> = {
  pending: { label: '等待中', type: 'info' },
  running: { label: '下载中', type: 'primary' },
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  paused: { label: '已暂停', type: 'warning' },
  skipped: { label: '已跳过', type: 'info', plain: true },
}

/** 批次状态（7 种） */
export const BATCH_STATUS_MAP: Record<string, StatusMeta> = {
  pending: { label: '等待中', type: 'info' },
  running: { label: '进行中', type: 'primary' },
  paused: { label: '已暂停', type: 'warning' },
  success: { label: '成功', type: 'success' },
  success_with_warning: { label: '成功(有警告)', type: 'warning' },
  failed: { label: '失败', type: 'danger' },
  paused_with_warning: { label: '暂停(有残留)', type: 'danger', plain: true },
}

/** 产物状态（4 种） */
export const ARTIFACT_STATUS_MAP: Record<string, StatusMeta> = {
  processing: { label: '处理中', type: 'primary' },
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  missing: { label: '文件缺失', type: 'info' },
}

/** 数据源健康度分级 */
export const HEALTH_LEVEL_MAP: Record<string, { label: string; color: string; tagType: TagType }> = {
  healthy: { label: '健康', color: '#67c23a', tagType: 'success' },
  sub_healthy: { label: '亚健康', color: '#e6a23c', tagType: 'warning' },
  unhealthy: { label: '异常', color: '#f56c6c', tagType: 'danger' },
  unknown: { label: '未知', color: '#c0c4cc', tagType: 'info' },
}

/** 内容类型（三套页面复用） */
export interface ContentTypeMeta {
  label: string
  shortLabel: string
  route: string
  icon: string
  /** 列表页「累计采集」列标题与单位 */
  countLabel: string
  countUnit: string
  /** 工作页标题 */
  workbenchTitle: string
  /** 空态引导文案 */
  emptyTip: string
}

export const CONTENT_TYPE_MAP: Record<string, ContentTypeMeta> = {
  video: {
    label: '视频',
    shortLabel: '视频',
    route: '/content/video',
    icon: 'VideoCamera',
    countLabel: '累计采集条数',
    countUnit: '条',
    workbenchTitle: '视频采集',
    emptyTip: '暂无视频类型数据源，去数据源页添加',
  },
  text: {
    label: '文字',
    shortLabel: '文字',
    route: '/content/text',
    icon: 'Document',
    countLabel: '累计采集章节数',
    countUnit: '章',
    workbenchTitle: '文字采集',
    emptyTip: '暂无文字类型数据源，去数据源页添加',
  },
  image: {
    label: '图片',
    shortLabel: '图片',
    route: '/content/image',
    icon: 'Picture',
    countLabel: '累计采集图集数',
    countUnit: '个',
    workbenchTitle: '图片采集',
    emptyTip: '暂无图片类型数据源，去数据源页添加',
  },
}

/** 策略（三种） */
export interface StrategyMeta {
  value: 'count' | 'page' | 'date'
  label: string
  desc: string
  icon: string
}

export const STRATEGY_MAP: StrategyMeta[] = [
  { value: 'count', label: '按指定条数', desc: '从上次记录之后开始，取 n 条', icon: 'Sort' },
  { value: 'page', label: '按分页', desc: '从起始页开始，连续取 pages 页', icon: 'Files' },
  { value: 'date', label: '按日期', desc: '取日期区间内全部条目，自动过滤已成功过的', icon: 'Calendar' },
]

/** 日志级别 */
export const LOG_LEVEL_OPTIONS = [
  { value: 'ALL', label: '全部' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARN', label: 'WARN' },
  { value: 'ERROR', label: 'ERROR' },
]

/** 批次终态（轮询到这些值必须停表） */
export const TERMINAL_BATCH_STATUSES = ['success', 'success_with_warning', 'failed']

/** 会占用数据的「进行中」批次状态（用于判断是否允许发起新批次） */
export const BUSY_BATCH_STATUSES = ['pending', 'running', 'paused', 'paused_with_warning']

/** 分页可选条数（PRD P0-20） */
export const PAGE_SIZES = [10, 20, 50]
export const DEFAULT_PAGE_SIZE = 10

/** 侧边栏菜单（7 项，顺序固定，path 与 router/index.ts 一一对应） */
export interface MenuItem {
  path: string
  label: string
  icon: string
  /** content 类型菜单额外标记 */
  type?: 'video' | 'text' | 'image'
}

export const MENU_ITEMS: MenuItem[] = [
  { path: '/', label: '首页', icon: 'HomeFilled' },
  { path: '/content/video', label: '视频', icon: 'VideoCamera', type: 'video' },
  { path: '/content/text', label: '文字', icon: 'Document', type: 'text' },
  { path: '/content/image', label: '图片', icon: 'Picture', type: 'image' },
  { path: '/artifacts', label: '产物', icon: 'FolderOpened' },
  { path: '/data-sources', label: '数据源', icon: 'Coin' },
  { path: '/settings', label: '设置', icon: 'Setting' },
]

/** 数据源类型选项（数据源页筛选/表单） */
export const SOURCE_TYPE_OPTIONS = [
  { value: 'video', label: '视频' },
  { value: 'text', label: '文字' },
  { value: 'image', label: '图片' },
]

/** 产物类型选项（产物页筛选用，含 pdf） */
export const ARTIFACT_TYPE_OPTIONS = [
  { value: 'video', label: '视频' },
  { value: 'text', label: '文字' },
  { value: 'pdf', label: 'PDF' },
  { value: 'image', label: '图片' },
]

/**
 * 错误码文案（与后端 `common/errors.py::ErrCode` 同步，仅用于本地兜底提示；
 * 正常展示一律用后端返回的 message）。
 */
export const ERROR_CODE_MAP: Record<number, string> = {
  0: '成功',
  1001: '参数不合法',
  1002: '文件格式不支持',
  1003: '文件超出大小限制',
  2001: '数据源不存在或已删除',
  2002: '同名同类地址的数据源已存在',
  2003: '该数据源有运行中的批次',
  3001: '该数据源有运行中的批次',
  3002: '待执行任务过多',
  3003: '未检测到 ffmpeg',
  3004: '批次不存在',
  3005: '批次当前状态不允许该操作',
  3006: '没有可重试的失败任务',
  3007: '仅失败的任务可以重试',
  3008: '起始页超出总页数',
  4001: '解析脚本执行异常',
  4002: '解析脚本执行超时',
  4003: '任务不存在',
  4004: '产物不存在',
  4005: '网络请求失败',
  4006: 'm3u8 解析失败',
  4007: 'DRM 加密暂不支持',
  4008: '磁盘空间不足',
  5000: '服务内部错误',
  5001: '系统操作失败',
  5002: '目标目录不可写',
}

/** 战略表单默认值上限（与后端 DEFAULTS 对齐，仅用于前端即时校验） */
export const LIMITS = {
  maxThreads: 32,
  minThreads: 1,
  countMax: 9999,
  pagesMax: 500,
  dateSpanDays: 365,
  pageSizeMax: 500,
}
