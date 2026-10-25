"""首页统计 DTO。"""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelModel


class HealthSummary(CamelModel):
    """健康源数 / 总数。"""

    healthy: int = 0
    total: int = 0


class RunningBatchItem(CamelModel):
    """首页运行中批次行。"""

    batch_id: int
    data_source_id: int
    data_source_name: str | None = None
    data_source_type: str | None = None
    strategy: str
    status: str
    phase: str
    progress: int = 0
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    elapsed_ms: int = 0
    created_at: str | None = None


class OverviewResp(CamelModel):
    """首页概览（单请求聚合）。"""

    health: HealthSummary = Field(default_factory=HealthSummary)
    today: int = 0
    week: int = 0
    month: int = 0
    running: list[RunningBatchItem] = Field(default_factory=list)


class TrendPoint(CamelModel):
    """趋势点。"""

    label: str
    count: int = 0


class TrendResp(CamelModel):
    """趋势出参。"""

    granularity: str = "day"
    points: list[TrendPoint] = Field(default_factory=list)


class HealthSourceItem(CamelModel):
    """数据源健康度行。"""

    data_source_id: int
    name: str
    type: str
    health_score: int | None = None
    success_rate_20: float | None = None
    last_success_at: str | None = None
    level: str = "unknown"
