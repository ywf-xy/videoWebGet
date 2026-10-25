"""任务 API：列表 / 详情 / 日志 / 单条与批量重试。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import PageDep, SessionDep
from app.schemas.common import PagePayload, Resp, SubmittedResp, ok
from app.schemas.task import (
    TaskDetail,
    TaskItem,
    TaskLogItem,
    TaskRetryPayload,
    TaskRetryResp,
)
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["task"])


@router.get("", response_model=Resp[PagePayload[TaskItem]], summary="任务列表")
def list_tasks(
    db: SessionDep,
    page: PageDep,
    batch_id: int | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
) -> dict:
    """支持批次/状态/关键字过滤（标题或地址），按 seq_no 升序。"""
    items, total = task_service.list_tasks(
        db,
        batch_id=batch_id,
        status=status,
        keyword=keyword,
        page=page.page,
        page_size=page.page_size,
    )
    return ok(
        PagePayload[TaskItem](items=items, total=total, page=page.page, pageSize=page.page_size)
    )


@router.post("/retry", response_model=Resp[SubmittedResp], summary="批量重试失败任务")
def retry_tasks(db: SessionDep, payload: TaskRetryPayload) -> dict:
    """返回 ``{submitted:n}``；全部不可重试返回 3007。"""
    return ok(task_service.retry_many(db, payload.task_ids))


@router.get("/{task_id}", response_model=Resp[TaskDetail], summary="任务详情")
def get_task(db: SessionDep, task_id: int) -> dict:
    """任务详情 + 结果记录。"""
    return ok(task_service.get_detail(db, task_id))


@router.get("/{task_id}/logs", response_model=Resp[list[TaskLogItem]], summary="任务日志")
def get_task_logs(
    db: SessionDep,
    task_id: int,
    level: str | None = Query(None),
    keyword: str | None = Query(None),
    page_size: int = Query(200, ge=1, le=1000, alias="pageSize"),
) -> dict:
    """按级别/关键字过滤，按时间升序返回。"""
    return ok(task_service.get_logs(db, task_id, level=level, keyword=keyword, page_size=page_size))


@router.post("/{task_id}/retry", response_model=Resp[TaskRetryResp], summary="单条重试")
def retry_task(db: SessionDep, task_id: int) -> dict:
    """仅 failed 可重试，否则 3007。"""
    return ok(task_service.retry(db, task_id))
