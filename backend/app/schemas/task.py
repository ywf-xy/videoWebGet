"""任务 DTO。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import CamelModel


class TaskItem(CamelModel):
    """任务列表项（含 step 进度与 extra 摘要）。"""

    id: int
    batch_id: int
    data_source_id: int
    seq_no: int
    title: str
    source_url: str
    status: str
    attempt_count: int = 0
    error_code: str | None = None
    error_msg: str | None = None
    step_done: int = 0
    step_total: int = 1
    duration_ms: int = 0
    file_size: int = 0
    file_count: int = 0
    word_count: int = 0
    image_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class TaskResultInfo(CamelModel):
    """任务结果。"""

    id: int
    artifact_type: str
    output_path: str
    file_size: int = 0
    file_count: int = 1
    fingerprint: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class TaskDetail(CamelModel):
    """任务详情 + 结果。"""

    id: int
    batch_id: int
    data_source_id: int
    seq_no: int
    title: str
    source_url: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    attempt_count: int = 0
    error_code: str | None = None
    error_msg: str | None = None
    step_done: int = 0
    step_total: int = 1
    duration_ms: int = 0
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result: TaskResultInfo | None = None


class TaskLogItem(CamelModel):
    """任务日志条目。"""

    id: int
    level: str
    message: str
    created_at: str
    task_id: int | None = None


class TaskRetryResp(CamelModel):
    """单条重试出参。"""

    status: str = "pending"
    attempt_count: int = 0


class TaskRetryPayload(CamelModel):
    """批量重试入参。"""

    task_ids: list[int] = Field(default_factory=list)
