"""健康度服务：近 20 次任务采样 → 健康分落库（每批次结束 / 定时刷新）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.common.timeutil import now_iso
from app.config import E
from app.db.models import CrawlTask, DataSource
from app.engine.health_calculator import SAMPLE_SIZE, HealthCalculator
from app.schemas.data_source import HealthResp

logger = get_logger(__name__)


def sample_statuses(db: Session, ds_id: int, limit: int = SAMPLE_SIZE) -> list[str]:
    """取该数据源最近 N 次已结束任务的状态（不含 pending/running）。"""
    rows = db.execute(
        select(CrawlTask.status)
        .where(
            CrawlTask.data_source_id == int(ds_id),
            CrawlTask.status.in_((E.TASK_SUCCESS, E.TASK_FAILED, E.TASK_SKIPPED)),
        )
        .order_by(CrawlTask.created_at.desc(), CrawlTask.id.desc())
        .limit(int(limit))
    ).all()
    return [str(row[0]) for row in rows]


def compute_and_store(db: Session, ds: DataSource) -> int | None:
    """重算并写回单个数据源的健康分与近 20 次成功率。"""
    statuses = sample_statuses(db, int(ds.id))
    score = HealthCalculator.compute(statuses, ds.last_success_at)
    rate = HealthCalculator.success_rate(statuses)
    ds.health_score = score
    ds.success_rate_20 = rate
    ds.updated_at = now_iso()
    return score


def get_detail(db: Session, ds_id: int) -> HealthResp:
    """读取健康度明细（sample_size 为实际采样条数）。"""
    ds = db.get(DataSource, int(ds_id))
    if ds is None:
        return HealthResp()
    statuses = sample_statuses(db, int(ds_id))
    return HealthResp(
        health_score=ds.health_score,
        success_rate_20=ds.success_rate_20,
        last_success_at=ds.last_success_at,
        sample_size=len(statuses),
    )


def refresh_all(db: Session) -> int:
    """全量刷新（定时任务 / 危险操作「重建统计缓存」）。"""
    sources = db.execute(
        select(DataSource).where(DataSource.is_deleted == 0)
    ).scalars().all()
    updated = 0
    for ds in sources:
        compute_and_store(db, ds)
        updated += 1
    db.commit()
    logger.info("健康度已刷新 %s 个数据源", updated)
    return updated
