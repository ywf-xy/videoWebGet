"""首页统计服务：概览（健康源/日周月/运行中批次）、趋势、健康度列表。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.common.timeutil import (
    day_start,
    day_start_iso,
    elapsed_ms,
    month_start,
    now,
    to_iso,
    week_start,
)
from app.config import E
from app.db.models import CrawlBatch, CrawlTask, DataSource
from app.engine.health_calculator import HealthCalculator
from app.schemas.dashboard import (
    HealthSourceItem,
    HealthSummary,
    OverviewResp,
    RunningBatchItem,
    TrendPoint,
    TrendResp,
)

logger = get_logger(__name__)


def _success_ts():
    """成功任务的统计时间列（优先 finished_at）。"""
    return func.coalesce(CrawlTask.finished_at, CrawlTask.created_at)


def _count_success_since(db: Session, start_iso: str) -> int:
    """统计某时间点之后成功的任务数。"""
    statement = select(func.count(CrawlTask.id)).where(
        CrawlTask.status == E.TASK_SUCCESS,
        _success_ts() >= start_iso,
    )
    return int(db.execute(statement).scalar() or 0)


def overview(db: Session) -> OverviewResp:
    """首页概览：单请求聚合（健康源数 / 日周月 / 运行中批次）。"""
    total_sources = int(
        db.execute(select(func.count(DataSource.id)).where(DataSource.is_deleted == 0)).scalar()
        or 0
    )
    healthy_sources = int(
        db.execute(
            select(func.count(DataSource.id)).where(
                DataSource.is_deleted == 0,
                DataSource.health_score.is_not(None),
                DataSource.health_score >= 80,
            )
        ).scalar()
        or 0
    )

    today = _count_success_since(db, day_start_iso())
    week = _count_success_since(db, to_iso(week_start()) or day_start_iso())
    month = _count_success_since(db, to_iso(month_start()) or day_start_iso())

    rows = db.execute(
        select(CrawlBatch, DataSource.name, DataSource.type)
        .join(DataSource, DataSource.id == CrawlBatch.data_source_id, isouter=True)
        .where(CrawlBatch.status.in_((E.BATCH_RUNNING, E.BATCH_PAUSED, E.BATCH_PAUSED_WITH_WARNING)))
        .order_by(CrawlBatch.created_at.desc())
        .limit(20)
    ).all()
    running = [
        RunningBatchItem(
            batch_id=int(batch.id),
            data_source_id=int(batch.data_source_id),
            data_source_name=name,
            data_source_type=ds_type,
            strategy=str(batch.strategy),
            status=str(batch.status),
            phase=str(batch.phase),
            progress=int(
                round(
                    int(batch.done_tasks or 0) * 100.0 / int(batch.total_tasks)
                    if int(batch.total_tasks or 0) > 0
                    else 0
                )
            ),
            total=int(batch.total_tasks or 0),
            done=int(batch.done_tasks or 0),
            failed=int(batch.failed_tasks or 0),
            skipped=int(batch.skipped_tasks or 0),
            elapsed_ms=elapsed_ms(batch.started_at or batch.created_at, batch.finished_at),
            created_at=batch.created_at,
        )
        for batch, name, ds_type in rows
    ]

    return OverviewResp(
        health=HealthSummary(healthy=healthy_sources, total=total_sources),
        today=today,
        week=week,
        month=month,
        running=running,
    )


def _bucket_rows(db: Session, start_iso: str, length: int) -> dict[str, int]:
    """按 ``substr(ts, 1, length)`` 聚合成功任务数。"""
    key = func.substr(_success_ts(), 1, int(length))
    rows = db.execute(
        select(key, func.count(CrawlTask.id))
        .where(CrawlTask.status == E.TASK_SUCCESS, _success_ts() >= start_iso)
        .group_by(key)
    ).all()
    return {str(row[0]): int(row[1]) for row in rows if row[0]}


def trend(db: Session, granularity: str = "day") -> TrendResp:
    """采集量趋势：日=今天 24 小时；周=本周每天；月=本月每天。"""
    mode = granularity if granularity in ("day", "week", "month") else "day"
    points: list[TrendPoint] = []

    if mode == "day":
        start = day_start()
        buckets = _bucket_rows(db, to_iso(start) or "", 13)  # yyyy-MM-ddTHH
        for hour in range(24):
            label = f"{hour:02d}:00"
            key = f"{start.strftime('%Y-%m-%d')}T{hour:02d}"
            points.append(TrendPoint(label=label, count=int(buckets.get(key, 0))))
        return TrendResp(granularity=mode, points=points)

    start = week_start() if mode == "week" else month_start()
    buckets = _bucket_rows(db, to_iso(start) or "", 10)  # yyyy-MM-dd
    current = start
    end = now()
    while current.date() <= end.date():
        key = current.strftime("%Y-%m-%d")
        points.append(TrendPoint(label=current.strftime("%m-%d"), count=int(buckets.get(key, 0))))
        current = current + timedelta(days=1)
    return TrendResp(granularity=mode, points=points)


def health_list(db: Session, order: str = "asc") -> list[HealthSourceItem]:
    """数据源健康度列表（无记录 health_score 为 null）。"""
    descending = str(order).lower() == "desc"
    score_column = DataSource.health_score
    ordering = (
        (score_column.is_(None), score_column.desc(), DataSource.id.asc())
        if descending
        else (score_column.is_(None), score_column.asc(), DataSource.id.asc())
    )
    rows = db.execute(
        select(DataSource).where(DataSource.is_deleted == 0).order_by(*ordering).limit(200)
    ).scalars().all()
    return [
        HealthSourceItem(
            data_source_id=int(ds.id),
            name=str(ds.name),
            type=str(ds.type),
            health_score=ds.health_score,
            success_rate_20=ds.success_rate_20,
            last_success_at=ds.last_success_at,
            level=HealthCalculator.level(ds.health_score),
        )
        for ds in rows
    ]
