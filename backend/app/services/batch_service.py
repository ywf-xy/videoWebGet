"""批次服务：创建（单飞/队列/ffmpeg 前置校验）、暂停恢复、进度聚合、日志、重试。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.common.timeutil import elapsed_ms, now_iso
from app.config import DEFAULTS, E
from app.db.models import CrawlBatch, CrawlTask, DataSource, TaskLog
from app.downloader.ffmpeg import get_ffmpeg
from app.engine.crawler_engine import get_engine
from app.schemas.batch import (
    ActiveTaskItem,
    BatchCreatedResp,
    BatchDetail,
    BatchItem,
    BatchLogItem,
    BatchLogsResp,
    BatchProgressInfo,
    BatchProgressResp,
    BatchStatusResp,
    BatchCreate,
    LatestBatchResp,
)
from app.services.setting_service import get_runtime

logger = get_logger(__name__)


def _progress_of(total: int, done: int) -> int:
    """进度百分比（四舍五入取整）。"""
    if total <= 0:
        return 0
    return int(round(done * 100.0 / total))


def _to_item(batch: CrawlBatch, ds_name: str | None, ds_type: str | None) -> BatchItem:
    """ORM → 列表项。"""
    total = int(batch.total_tasks or 0)
    done = int(batch.done_tasks or 0)
    return BatchItem(
        id=int(batch.id),
        data_source_id=int(batch.data_source_id),
        data_source_name=ds_name,
        data_source_type=ds_type,
        strategy=str(batch.strategy),
        status=str(batch.status),
        phase=str(batch.phase),
        total_tasks=total,
        done_tasks=done,
        failed_tasks=int(batch.failed_tasks or 0),
        skipped_tasks=int(batch.skipped_tasks or 0),
        progress=_progress_of(total, done),
        threads=int(batch.threads or 1),
        created_at=batch.created_at,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
    )


def get_entity(db: Session, batch_id: int) -> CrawlBatch:
    """按 id 取批次，不存在抛 3004。"""
    batch = db.get(CrawlBatch, int(batch_id))
    if batch is None:
        raise BizError(ErrCode.BATCH_NOT_FOUND)
    return batch


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------
def _single_flight_error(db: Session, ds_id: int, detail: str = "") -> BizError:
    """构造 3001 业务异常，消息里带上「已占用批次 id」方便前端提示与排查。"""
    occupant = db.execute(
        select(CrawlBatch.id)
        .where(
            CrawlBatch.data_source_id == int(ds_id),
            CrawlBatch.status.in_(E.BATCH_BUSY_STATUSES),
        )
        .order_by(CrawlBatch.id.desc())
        .limit(1)
    ).first()
    hint = f"（占用批次 #{int(occupant[0])}）" if occupant is not None else ""
    return BizError(
        ErrCode.BATCH_SINGLE_FLIGHT,
        f"该数据源有运行中的批次{hint}，请先暂停或等待完成",
        detail=detail or f"data_source_id={ds_id}",
    )


def create(db: Session, payload: BatchCreate) -> BatchCreatedResp:
    """创建批次并立即提交引擎执行。"""
    ds = db.get(DataSource, int(payload.data_source_id))
    if ds is None or int(ds.is_deleted) == 1:
        raise BizError(ErrCode.DS_NOT_FOUND)
    if int(ds.enabled) != 1:
        raise BizError(ErrCode.PARAM_INVALID, "数据源已停用，请先启用后再发起采集")

    # 单飞（快速失败）：同数据源存在 pending/running/paused 批次时直接拒绝；
    # 并发穿透由下面的 uq_batch_active 唯一索引兜底。
    busy = db.execute(
        select(CrawlBatch.id)
        .where(
            CrawlBatch.data_source_id == int(ds.id),
            CrawlBatch.status.in_(E.BATCH_BUSY_STATUSES),
        )
        .limit(1)
    ).first()
    if busy is not None:
        raise _single_flight_error(db, int(ds.id))

    pending_total = int(
        db.execute(
            select(func.count(CrawlTask.id)).where(CrawlTask.status == E.TASK_PENDING)
        ).scalar()
        or 0
    )
    if pending_total > int(DEFAULTS["queue.max_pending"]):
        raise BizError(ErrCode.QUEUE_FULL)

    if str(ds.type) == E.TYPE_VIDEO and not get_ffmpeg().available:
        raise BizError(ErrCode.FFMPEG_MISSING)

    runtime = get_runtime(db)
    export_format = payload.export_format
    if str(ds.type) != E.TYPE_TEXT:
        export_format = None
    elif export_format not in E.EXPORT_FORMATS:
        export_format = E.FORMAT_TXT

    batch = CrawlBatch(
        data_source_id=int(ds.id),
        strategy=payload.strategy,
        strategy_params=dict(payload.strategy_params or {}),
        export_format=export_format,
        status=E.BATCH_PENDING,
        phase=E.PHASE_PARSE,
        threads=max(1, min(runtime.max_threads, int(DEFAULTS["max_threads_limit"]))),
        request_url=str(ds.current_url or ds.homepage_url),
        total_tasks=0,
        done_tasks=0,
        failed_tasks=0,
        skipped_tasks=0,
        warnings=[],
    )
    try:
        db.add(batch)
        db.commit()
    except IntegrityError as exc:
        # 上面的 SELECT 只是「快速失败」的友好提示；真正的互斥由
        # uq_batch_active(partial unique index) 保证，并发请求在这里被数据库拦下。
        db.rollback()
        logger.info(
            "single-flight：数据源 #%s 并发抢跑，已被数据库唯一约束拦下 → 3001", ds.id
        )
        raise _single_flight_error(
            db, int(ds.id), detail=f"data_source_id={ds.id}；冲突来源=uq_batch_active"
        ) from exc
    db.refresh(batch)
    batch_id = int(batch.id)

    get_engine().submit_batch(batch_id, int(batch.threads))
    logger.info(
        "创建批次 #%s：数据源 #%s，策略 %s，线程 %s",
        batch_id,
        ds.id,
        payload.strategy,
        batch.threads,
    )
    return BatchCreatedResp(batch_id=batch_id, status=E.BATCH_PENDING)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def list_batches(
    db: Session,
    *,
    data_source_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[BatchItem], int]:
    """分页查询批次（按创建时间倒序）。"""
    conditions: list[Any] = []
    if data_source_id is not None:
        conditions.append(CrawlBatch.data_source_id == int(data_source_id))
    if status:
        conditions.append(CrawlBatch.status == status)

    total = int(
        db.execute(select(func.count(CrawlBatch.id)).where(*conditions)).scalar() or 0
    )
    rows = db.execute(
        select(CrawlBatch, DataSource.name, DataSource.type)
        .join(DataSource, DataSource.id == CrawlBatch.data_source_id, isouter=True)
        .where(*conditions)
        .order_by(CrawlBatch.created_at.desc(), CrawlBatch.id.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).all()
    return [_to_item(batch, name, ds_type) for batch, name, ds_type in rows], total


def get_detail(db: Session, batch_id: int) -> BatchDetail:
    """批次详情。"""
    batch = get_entity(db, batch_id)
    ds = db.get(DataSource, int(batch.data_source_id))
    total = int(batch.total_tasks or 0)
    done = int(batch.done_tasks or 0)
    return BatchDetail(
        id=int(batch.id),
        data_source_id=int(batch.data_source_id),
        data_source_name=ds.name if ds else None,
        data_source_type=ds.type if ds else None,
        strategy=str(batch.strategy),
        strategy_params=dict(batch.strategy_params or {}),
        export_format=batch.export_format,
        status=str(batch.status),
        phase=str(batch.phase),
        total_tasks=total,
        done_tasks=done,
        failed_tasks=int(batch.failed_tasks or 0),
        skipped_tasks=int(batch.skipped_tasks or 0),
        progress=_progress_of(total, done),
        threads=int(batch.threads or 1),
        request_url=batch.request_url,
        cursor_before=batch.cursor_before,
        cursor_after=batch.cursor_after,
        error_code=batch.error_code,
        error_msg=batch.error_msg,
        warnings=list(batch.warnings or []),
        pause_requested_at=batch.pause_requested_at,
        started_at=batch.started_at,
        finished_at=batch.finished_at,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def progress(
    db: Session, batch_id: int, after_log_id: int | None = None
) -> BatchProgressResp:
    """进度轮询聚合（批次进度 + 活跃任务 + 增量日志）。"""
    batch = get_entity(db, batch_id)
    total = int(batch.total_tasks or 0)
    done = int(batch.done_tasks or 0)
    info = BatchProgressInfo(
        status=str(batch.status),
        phase=str(batch.phase),
        progress=_progress_of(total, done),
        total=total,
        done=done,
        failed=int(batch.failed_tasks or 0),
        skipped=int(batch.skipped_tasks or 0),
        elapsed_ms=elapsed_ms(batch.started_at or batch.created_at, batch.finished_at),
    )

    running = db.execute(
        select(CrawlTask)
        .where(CrawlTask.batch_id == int(batch.id), CrawlTask.status == E.TASK_RUNNING)
        .order_by(CrawlTask.seq_no.asc())
        .limit(20)
    ).scalars().all()
    active = [
        ActiveTaskItem(
            task_id=int(task.id),
            title=str(task.title),
            step_done=int(task.step_done or 0),
            step_total=max(1, int(task.step_total or 1)),
        )
        for task in running
    ]

    logs: list[BatchLogItem] | None = None
    last_log_id = int(after_log_id or 0)
    if after_log_id is not None:
        rows = db.execute(
            select(TaskLog)
            .where(TaskLog.batch_id == int(batch.id), TaskLog.id > int(after_log_id))
            .order_by(TaskLog.id.asc())
            .limit(200)
        ).scalars().all()
        logs = [
            BatchLogItem(
                id=int(log.id),
                level=str(log.level),
                message=str(log.message),
                task_id=log.task_id,
                created_at=str(log.created_at),
            )
            for log in rows
        ]
        if logs:
            last_log_id = int(logs[-1].id)

    return BatchProgressResp(batch=info, active=active, logs=logs, last_log_id=last_log_id)


# ---------------------------------------------------------------------------
# 控制
# ---------------------------------------------------------------------------
def pause(db: Session, batch_id: int) -> BatchStatusResp:
    """请求暂停（状态必须为 pending/running）。"""
    batch = get_entity(db, batch_id)
    if batch.status not in (E.BATCH_PENDING, E.BATCH_RUNNING):
        raise BizError(
            ErrCode.BATCH_STATE_INVALID,
            f"批次当前状态为 {batch.status}，无法暂停",
        )
    batch.status = E.BATCH_PAUSED
    batch.pause_requested_at = now_iso()
    batch.updated_at = now_iso()
    db.commit()
    get_engine().pause_batch(int(batch.id))
    logger.info("批次 #%s 请求暂停", batch.id)
    return BatchStatusResp(status=E.BATCH_PAUSED)


def resume(db: Session, batch_id: int) -> BatchStatusResp:
    """恢复批次（状态必须为 paused/paused_with_warning）。"""
    batch = get_entity(db, batch_id)
    if batch.status not in (E.BATCH_PAUSED, E.BATCH_PAUSED_WITH_WARNING):
        raise BizError(
            ErrCode.BATCH_STATE_INVALID,
            f"批次当前状态为 {batch.status}，无法恢复",
        )
    engine = get_engine()
    # 暂停收尾可能仍在进行（活跃任务正在回退），等旧执行体退出后再接管，避免双执行体
    if not engine.wait_runner_exit(int(batch.id), float(DEFAULTS["pause.timeout_s"]) + 5):
        raise BizError(
            ErrCode.BATCH_STATE_INVALID,
            "批次正在暂停收尾（仍有任务未结束），请稍后重试恢复",
        )
    runtime = get_runtime(db)
    threads = max(1, min(int(batch.threads or DEFAULTS["max_threads"]), runtime.max_threads))
    batch.threads = threads
    batch.status = E.BATCH_RUNNING
    batch.pause_requested_at = None
    batch.updated_at = now_iso()
    db.commit()
    engine.resume_batch(int(batch.id))
    if not engine.is_running(int(batch.id)):
        engine.submit_batch(int(batch.id), threads)
    logger.info("批次 #%s 恢复执行（线程 %s）", batch.id, threads)
    return BatchStatusResp(status=E.BATCH_RUNNING)


def retry_failed(db: Session, batch_id: int) -> int:
    """重试批次内全部失败任务，返回提交条数。"""
    batch = get_entity(db, batch_id)
    rows = db.execute(
        select(CrawlTask.id).where(
            CrawlTask.batch_id == int(batch.id), CrawlTask.status == E.TASK_FAILED
        )
    ).all()
    task_ids = [int(row[0]) for row in rows]
    if not task_ids:
        raise BizError(ErrCode.NOTHING_TO_RETRY)
    submitted = get_engine().retry_tasks(task_ids)
    logger.info("批次 #%s 重试失败任务 %s 条", batch.id, submitted)
    return submitted


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def logs(
    db: Session,
    batch_id: int,
    *,
    level: str | None = None,
    keyword: str | None = None,
    after_id: int | None = None,
    page_size: int = 200,
) -> BatchLogsResp:
    """批次日志（按 id 升序；after_id 用于增量拉取）。"""
    batch = get_entity(db, batch_id)
    conditions: list[Any] = [TaskLog.batch_id == int(batch.id)]
    if level and level in E.LOG_LEVELS:
        conditions.append(TaskLog.level == level)
    if keyword:
        conditions.append(TaskLog.message.like(f"%{keyword.strip()}%"))
    if after_id is not None:
        conditions.append(TaskLog.id > int(after_id))
    rows = db.execute(
        select(TaskLog)
        .where(*conditions)
        .order_by(TaskLog.id.desc() if after_id is None else TaskLog.id.asc())
        .limit(max(1, int(page_size)))
    ).scalars().all()
    items = [
        BatchLogItem(
            id=int(log.id),
            level=str(log.level),
            message=str(log.message),
            task_id=log.task_id,
            created_at=str(log.created_at),
        )
        for log in rows
    ]
    if after_id is None:
        items.reverse()
    return BatchLogsResp(
        items=items, last_id=int(items[-1].id) if items else int(after_id or 0)
    )


# ---------------------------------------------------------------------------
# 工作页「上次采集到」
# ---------------------------------------------------------------------------
def latest(db: Session, data_source_id: int) -> LatestBatchResp:
    """最近一次批次摘要（无历史返回 has_history=False）。"""
    ds = db.get(DataSource, int(data_source_id))
    if ds is None or int(ds.is_deleted) == 1:
        raise BizError(ErrCode.DS_NOT_FOUND)
    batch = db.execute(
        select(CrawlBatch)
        .where(CrawlBatch.data_source_id == int(ds.id))
        .order_by(CrawlBatch.created_at.desc(), CrawlBatch.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if batch is None:
        return LatestBatchResp(has_history=False)

    cursor_after = dict(batch.cursor_after or {})
    last_title: str | None = None
    last_task = db.execute(
        select(CrawlTask.title)
        .where(CrawlTask.batch_id == int(batch.id), CrawlTask.status == E.TASK_SUCCESS)
        .order_by(CrawlTask.seq_no.desc())
        .limit(1)
    ).first()
    if last_task is not None:
        last_title = str(last_task[0])

    return LatestBatchResp(
        has_history=True,
        batch_id=int(batch.id),
        status=str(batch.status),
        strategy=str(batch.strategy),
        finished_at=batch.finished_at,
        last_item_no=int(cursor_after.get("last_item_no") or ds.cursor_last_item_no or 0),
        last_page=int(cursor_after.get("last_page") or ds.cursor_last_page or 0),
        last_success_date=cursor_after.get("last_success_date") or ds.cursor_last_success_date,
        last_item_title=last_title,
        done_tasks=int(batch.done_tasks or 0),
        failed_tasks=int(batch.failed_tasks or 0),
    )
