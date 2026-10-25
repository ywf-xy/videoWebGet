"""批次 DTO。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from app.common.timeutil import parse_date
from app.config import DEFAULTS
from app.schemas.common import CamelModel

Strategy = Literal["count", "page", "date"]
ExportFormat = Literal["txt", "pdf"]


class BatchCreate(CamelModel):
    """创建批次入参（策略参数在服务端二次校验）。"""

    data_source_id: int
    strategy: Strategy
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    export_format: ExportFormat | None = None

    @model_validator(mode="after")
    def _check_params(self) -> "BatchCreate":
        params = self.strategy_params or {}
        if self.strategy == "count":
            n = params.get("n")
            try:
                n_int = int(n)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError("条数 n 必须为整数") from exc
            if not 1 <= n_int <= int(DEFAULTS["strategy.n_max"]):
                raise ValueError(f"条数需在 1-{DEFAULTS['strategy.n_max']} 之间")
        elif self.strategy == "page":
            try:
                start = int(params.get("start", 0))
                pages = int(params.get("pages", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("起始页与页数必须为整数") from exc
            if start < 1:
                raise ValueError("起始页需 ≥ 1")
            if not 1 <= pages <= int(DEFAULTS["strategy.pages_max"]):
                raise ValueError(f"页数需在 1-{DEFAULTS['strategy.pages_max']} 之间")
        else:
            date_from = parse_date(str(params.get("from") or ""))
            date_to = parse_date(str(params.get("to") or ""))
            if date_from is None or date_to is None:
                raise ValueError("开始日期与结束日期必须为 yyyy-MM-dd 格式")
            if date_to < date_from:
                raise ValueError("结束日期不能早于开始日期")
            if (date_to - date_from).days > int(DEFAULTS["strategy.date_span_days"]):
                raise ValueError("日期跨度不能超过 365 天")
        return self


class BatchCreatedResp(CamelModel):
    """创建批次出参。"""

    batch_id: int
    status: str = "pending"


class BatchItem(CamelModel):
    """批次列表项。"""

    id: int
    data_source_id: int
    data_source_name: str | None = None
    data_source_type: str | None = None
    strategy: str
    status: str
    phase: str
    total_tasks: int = 0
    done_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    progress: int = 0
    threads: int = 1
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class BatchDetail(CamelModel):
    """批次详情。"""

    id: int
    data_source_id: int
    data_source_name: str | None = None
    data_source_type: str | None = None
    strategy: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    export_format: str | None = None
    status: str
    phase: str
    total_tasks: int = 0
    done_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    progress: int = 0
    threads: int = 1
    request_url: str | None = None
    cursor_before: dict[str, Any] | None = None
    cursor_after: dict[str, Any] | None = None
    error_code: str | None = None
    error_msg: str | None = None
    warnings: list[str] = Field(default_factory=list)
    pause_requested_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BatchProgressInfo(CamelModel):
    """进度卡数据。"""

    status: str
    phase: str
    progress: int = 0
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    elapsed_ms: int = 0


class ActiveTaskItem(CamelModel):
    """运行中任务的步骤进度。"""

    task_id: int
    title: str
    step_done: int = 0
    step_total: int = 1


class BatchLogItem(CamelModel):
    """批次/任务日志条目。"""

    id: int
    level: str
    message: str
    task_id: int | None = None
    created_at: str


class BatchProgressResp(CamelModel):
    """进度轮询出参（含可选增量日志）。"""

    batch: BatchProgressInfo
    active: list[ActiveTaskItem] = Field(default_factory=list)
    logs: list[BatchLogItem] | None = None
    last_log_id: int = 0


class BatchLogsResp(CamelModel):
    """批次日志列表。"""

    items: list[BatchLogItem] = Field(default_factory=list)
    last_id: int = 0


class BatchStatusResp(CamelModel):
    """暂停/恢复出参。"""

    status: str


class LatestBatchResp(CamelModel):
    """工作页「上次采集到」摘要。"""

    has_history: bool = False
    batch_id: int | None = None
    status: str | None = None
    strategy: str | None = None
    finished_at: str | None = None
    last_item_no: int = 0
    last_page: int = 0
    last_success_date: str | None = None
    last_item_title: str | None = None
    done_tasks: int = 0
    failed_tasks: int = 0
