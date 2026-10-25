"""任务服务：列表（含结果摘要）、详情、日志、单条/批量重试。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.config import E
from app.db.models import CrawlTask, TaskLog, TaskResult
from app.engine.crawler_engine import get_engine
from app.schemas.task import TaskDetail, TaskItem, TaskLogItem, TaskResultInfo, TaskRetryResp
from app.schemas.common import SubmittedResp

logger = get_logger(__name__)


def _extra_of(result: TaskResult | None) -> dict[str, Any]:
    """结果附加字段（时长 / 字数 / 图片数）。"""
    return dict(result.extra or {}) if result is not None else {}


def _to_item(task: CrawlTask, result: TaskResult | None) -> TaskItem:
    """ORM → 列表项。"""
    extra = _extra_of(result)
    return TaskItem(
        id=int(task.id),
        batch_id=int(task.batch_id),
        data_source_id=int(task.data_source_id),
        seq_no=int(task.seq_no or 0),
        title=str(task.title),
        source_url=str(task.source_url),
        status=str(task.status),
        attempt_count=int(task.attempt_count or 0),
        error_code=task.error_code,
        error_msg=task.error_msg,
        step_done=int(task.step_done or 0),
        step_total=max(1, int(task.step_total or 1)),
        duration_ms=int(task.duration_ms or 0),
        file_size=int(result.file_size) if result else 0,
        file_count=int(result.file_count) if result else 0,
        word_count=int(extra.get("word_count") or 0),
        image_count=int(extra.get("image_count") or extra.get("image_total") or 0),
        extra=extra,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


def list_tasks(
    db: Session,
    *,
    batch_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[TaskItem], int]:
    """分页查询任务（按 seq_no 升序）。"""
    conditions: list[Any] = []
    if batch_id is not None:
        conditions.append(CrawlTask.batch_id == int(batch_id))
    if status:
        conditions.append(CrawlTask.status == status)
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(or_(CrawlTask.title.like(like), CrawlTask.source_url.like(like)))

    total = int(
        db.execute(select(func.count(CrawlTask.id)).where(*conditions)).scalar() or 0
    )
    rows = db.execute(
        select(CrawlTask, TaskResult)
        .join(TaskResult, TaskResult.task_id == CrawlTask.id, isouter=True)
        .where(*conditions)
        .order_by(CrawlTask.seq_no.asc(), CrawlTask.id.asc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).all()
    return [_to_item(task, result) for task, result in rows], total


def get_detail(db: Session, task_id: int) -> TaskDetail:
    """任务详情（含结果）。"""
    task = db.get(CrawlTask, int(task_id))
    if task is None:
        raise BizError(ErrCode.TASK_NOT_FOUND)
    result = db.execute(
        select(TaskResult).where(TaskResult.task_id == int(task.id)).limit(1)
    ).scalar_one_or_none()
    return TaskDetail(
        id=int(task.id),
        batch_id=int(task.batch_id),
        data_source_id=int(task.data_source_id),
        seq_no=int(task.seq_no or 0),
        title=str(task.title),
        source_url=str(task.source_url),
        payload=dict(task.payload or {}),
        status=str(task.status),
        attempt_count=int(task.attempt_count or 0),
        error_code=task.error_code,
        error_msg=task.error_msg,
        step_done=int(task.step_done or 0),
        step_total=max(1, int(task.step_total or 1)),
        duration_ms=int(task.duration_ms or 0),
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        result=TaskResultInfo(
            id=int(result.id),
            artifact_type=str(result.artifact_type),
            output_path=str(result.output_path),
            file_size=int(result.file_size or 0),
            file_count=int(result.file_count or 1),
            fingerprint=result.fingerprint,
            extra=dict(result.extra or {}),
            created_at=result.created_at,
        )
        if result is not None
        else None,
    )


def get_logs(
    db: Session,
    task_id: int,
    *,
    level: str | None = None,
    keyword: str | None = None,
    page_size: int = 200,
) -> list[TaskLogItem]:
    """任务日志（按 id 升序）。"""
    task = db.get(CrawlTask, int(task_id))
    if task is None:
        raise BizError(ErrCode.TASK_NOT_FOUND)
    conditions: list[Any] = [TaskLog.task_id == int(task.id)]
    if level and level in E.LOG_LEVELS:
        conditions.append(TaskLog.level == level)
    if keyword:
        conditions.append(TaskLog.message.like(f"%{keyword.strip()}%"))
    rows = db.execute(
        select(TaskLog)
        .where(*conditions)
        .order_by(TaskLog.id.desc())
        .limit(max(1, int(page_size)))
    ).scalars().all()
    items = [
        TaskLogItem(
            id=int(log.id),
            level=str(log.level),
            message=str(log.message),
            created_at=str(log.created_at),
            task_id=log.task_id,
        )
        for log in rows
    ]
    items.reverse()
    return items


def retry(db: Session, task_id: int) -> TaskRetryResp:
    """单条重试（仅 failed 可重试）。"""
    task = db.get(CrawlTask, int(task_id))
    if task is None:
        raise BizError(ErrCode.TASK_NOT_FOUND)
    if task.status != E.TASK_FAILED:
        raise BizError(
            ErrCode.TASK_NOT_RETRYABLE, f"任务当前状态为 {task.status}，仅失败任务可重试"
        )
    get_engine().retry_tasks([int(task.id)])
    db.refresh(task)
    return TaskRetryResp(status=str(task.status), attempt_count=int(task.attempt_count or 0))


def retry_many(db: Session, task_ids: list[int]) -> SubmittedResp:
    """批量重试（忽略非 failed 任务；全部不可重试时抛 3007）。"""
    if not task_ids:
        raise BizError(ErrCode.PARAM_INVALID, "请选择要重试的任务")
    rows = db.execute(
        select(CrawlTask.id).where(
            CrawlTask.id.in_([int(item) for item in task_ids]),
            CrawlTask.status == E.TASK_FAILED,
        )
    ).all()
    retryable = [int(row[0]) for row in rows]
    if not retryable:
        raise BizError(ErrCode.TASK_NOT_RETRYABLE, "所选任务中没有可重试的失败任务")
    submitted = get_engine().retry_tasks(retryable)
    return SubmittedResp(submitted=submitted)
