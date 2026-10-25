"""业务错误码与统一异常（错误码分段见 ARCHITECTURE §4.7）。"""

from __future__ import annotations

from enum import IntEnum
from typing import Final


class ErrCode(IntEnum):
    """业务错误码。0 = 成功，其余分段：1xxx 入参、2xxx 数据源、3xxx 调度、4xxx 解析下载、5xxx 系统。"""

    OK = 0

    # ---- 1xxx 入参 / 格式 ----
    PARAM_INVALID = 1001
    FILE_FORMAT = 1002
    FILE_TOO_LARGE = 1003

    # ---- 2xxx 数据源 ----
    DS_NOT_FOUND = 2001
    DS_DUPLICATE = 2002
    DS_BUSY = 2003

    # ---- 3xxx 批次 / 调度 ----
    BATCH_SINGLE_FLIGHT = 3001
    QUEUE_FULL = 3002
    FFMPEG_MISSING = 3003
    BATCH_NOT_FOUND = 3004
    BATCH_STATE_INVALID = 3005
    NOTHING_TO_RETRY = 3006
    TASK_NOT_RETRYABLE = 3007
    PAGE_OUT_OF_RANGE = 3008

    # ---- 4xxx 解析 / 下载 ----
    SCRIPT_ERROR = 4001
    SCRIPT_TIMEOUT = 4002
    TASK_NOT_FOUND = 4003
    ARTIFACT_NOT_FOUND = 4004
    HTTP_ERROR = 4005
    M3U8_PARSE = 4006
    DRM_UNSUPPORTED = 4007
    DISK_FULL = 4008

    # ---- 5xxx 系统 ----
    INTERNAL = 5000
    OS_ACTION_FAILED = 5001
    PATH_NOT_WRITABLE = 5002


#: 默认中文人话（前端可直接 toast）
DEFAULT_MESSAGES: Final[dict[int, str]] = {
    ErrCode.OK: "ok",
    ErrCode.PARAM_INVALID: "参数不合法",
    ErrCode.FILE_FORMAT: "文件格式不支持",
    ErrCode.FILE_TOO_LARGE: "文件超出大小限制",
    ErrCode.DS_NOT_FOUND: "数据源不存在或已删除",
    ErrCode.DS_DUPLICATE: "同名同类地址的数据源已存在",
    ErrCode.DS_BUSY: "该数据源有运行中的批次，请先暂停或等待完成",
    ErrCode.BATCH_SINGLE_FLIGHT: "该数据源有运行中的批次，请先暂停或等待完成",
    ErrCode.QUEUE_FULL: "待执行任务过多，请先处理现有批次",
    ErrCode.FFMPEG_MISSING: "未检测到 ffmpeg，无法把 m3u8 转为 MP4，请先安装 ffmpeg 并加入 PATH",
    ErrCode.BATCH_NOT_FOUND: "批次不存在",
    ErrCode.BATCH_STATE_INVALID: "批次当前状态不允许该操作",
    ErrCode.NOTHING_TO_RETRY: "没有可重试的失败任务",
    ErrCode.TASK_NOT_RETRYABLE: "仅失败的任务可以重试",
    ErrCode.PAGE_OUT_OF_RANGE: "起始页超出总页数",
    ErrCode.SCRIPT_ERROR: "解析脚本执行异常",
    ErrCode.SCRIPT_TIMEOUT: "解析脚本执行超时",
    ErrCode.TASK_NOT_FOUND: "任务不存在",
    ErrCode.ARTIFACT_NOT_FOUND: "产物不存在",
    ErrCode.HTTP_ERROR: "网络请求失败",
    ErrCode.M3U8_PARSE: "m3u8 播放列表解析失败",
    ErrCode.DRM_UNSUPPORTED: "该视频使用 SAMPLE-AES / DRM 加密，暂不支持下载",
    ErrCode.DISK_FULL: "磁盘空间不足",
    ErrCode.INTERNAL: "服务内部错误",
    ErrCode.OS_ACTION_FAILED: "系统操作失败",
    ErrCode.PATH_NOT_WRITABLE: "目标目录不可写",
}

#: 可自动重试的错误码（PRD 9.5：连接超时 / 5xx / 分片失败 / m3u8 解析失败）
RETRYABLE_CODES: Final[frozenset[int]] = frozenset(
    {int(ErrCode.HTTP_ERROR), int(ErrCode.M3U8_PARSE)}
)

#: 业务码 → HTTP 状态码
HTTP_STATUS_MAP: Final[dict[int, int]] = {
    int(ErrCode.OK): 200,
    int(ErrCode.PARAM_INVALID): 400,
    int(ErrCode.FILE_FORMAT): 400,
    int(ErrCode.FILE_TOO_LARGE): 400,
    int(ErrCode.DS_NOT_FOUND): 404,
    int(ErrCode.DS_DUPLICATE): 409,
    int(ErrCode.DS_BUSY): 409,
    int(ErrCode.BATCH_SINGLE_FLIGHT): 409,
    int(ErrCode.QUEUE_FULL): 409,
    int(ErrCode.FFMPEG_MISSING): 400,
    int(ErrCode.BATCH_NOT_FOUND): 404,
    int(ErrCode.BATCH_STATE_INVALID): 409,
    int(ErrCode.NOTHING_TO_RETRY): 409,
    int(ErrCode.TASK_NOT_RETRYABLE): 409,
    int(ErrCode.PAGE_OUT_OF_RANGE): 400,
    int(ErrCode.SCRIPT_ERROR): 400,
    int(ErrCode.SCRIPT_TIMEOUT): 408,
    int(ErrCode.TASK_NOT_FOUND): 404,
    int(ErrCode.ARTIFACT_NOT_FOUND): 404,
    int(ErrCode.HTTP_ERROR): 502,
    int(ErrCode.M3U8_PARSE): 400,
    int(ErrCode.DRM_UNSUPPORTED): 400,
    int(ErrCode.DISK_FULL): 507,
    int(ErrCode.INTERNAL): 500,
    int(ErrCode.OS_ACTION_FAILED): 500,
    int(ErrCode.PATH_NOT_WRITABLE): 500,
}


def http_status_for(code: int) -> int:
    """返回业务码对应的 HTTP 状态码。"""
    return HTTP_STATUS_MAP.get(int(code), 400)


def message_for(code: int) -> str:
    """返回业务码的默认中文描述。"""
    return DEFAULT_MESSAGES.get(int(code), "未知错误")


class BizError(Exception):
    """业务异常：携带错误码、人话描述、可重试标记与可选 traceback 摘要。"""

    def __init__(
        self,
        code: int | ErrCode,
        message: str | None = None,
        *,
        retryable: bool | None = None,
        http_status: int | None = None,
        detail: str = "",
    ) -> None:
        self.code: int = int(code)
        self.message: str = message or message_for(self.code)
        self.detail: str = detail
        if retryable is None:
            self.retryable: bool = self.code in RETRYABLE_CODES
        else:
            self.retryable = retryable
        self.http_status: int = http_status if http_status is not None else http_status_for(self.code)
        super().__init__(f"[{self.code}] {self.message}")

    def to_payload(self) -> dict[str, object]:
        """转换为统一响应体。"""
        return {"code": self.code, "data": None, "message": self.message}

    def __str__(self) -> str:  # pragma: no cover - 仅日志展示
        return f"[{self.code}] {self.message}"


class PauseRequested(Exception):
    """暂停信号：任务在原子步骤结束时抛出，由调度器把任务回退为 pending。

    说明：这不是错误，仅用于跨层传递「用户已请求暂停」的控制流。
    """

    def __init__(self, message: str = "批次已暂停") -> None:
        self.message = message
        super().__init__(message)


def raise_if(condition: bool, code: int | ErrCode, message: str | None = None) -> None:
    """条件成立时抛出业务异常（简化校验代码）。"""
    if condition:
        raise BizError(code, message)
