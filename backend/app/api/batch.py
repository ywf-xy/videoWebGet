"""批次 API：创建 / 列表 / 详情 / 进度 / 暂停恢复 / 重试 / 日志 / 最近批次。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import PageDep, SessionDep
from app.schemas.batch import (
    BatchCreate,
    BatchCreatedResp,
    BatchDetail,
    BatchItem,
    BatchLogsResp,
    BatchProgressResp,
    BatchStatusResp,
    LatestBatchResp,
)
from app.schemas.common import PagePayload, Resp, SubmittedResp, ok
from app.services import batch_service

router = APIRouter(prefix="/batches", tags=["batch"])


@router.post("", response_model=Resp[BatchCreatedResp], summary="创建批次并开始采集")
def create_batch(db: SessionDep, payload: BatchCreate) -> dict:
    """创建批次：单飞冲突 3001、队列超限 3002、ffmpeg 缺失 3003。"""
    return ok(batch_service.create(db, payload))


@router.get("", response_model=Resp[PagePayload[BatchItem]], summary="批次列表")
def list_batches(
    db: SessionDep,
    page: PageDep,
    data_source_id: int | None = Query(None),
    status: str | None = Query(None),
) -> dict:
    """按创建时间倒序分页查询批次。"""
    items, total = batch_service.list_batches(
        db,
        data_source_id=data_source_id,
        status=status,
        page=page.page,
        page_size=page.page_size,
    )
    return ok(
        PagePayload[BatchItem](items=items, total=total, page=page.page, pageSize=page.page_size)
    )


@router.get("/latest", response_model=Resp[LatestBatchResp], summary="最近一次批次摘要")
def latest_batch(db: SessionDep, data_source_id: int = Query(..., description="数据源 id")) -> dict:
    """工作页「上次采集到」：无历史返回 has_history=false。"""
    return ok(batch_service.latest(db, data_source_id))


@router.get("/{batch_id}", response_model=Resp[BatchDetail], summary="批次详情")
def get_batch(db: SessionDep, batch_id: int) -> dict:
    """含 strategy_params、游标前后、warnings 与计数。"""
    return ok(batch_service.get_detail(db, batch_id))


@router.get(
    "/{batch_id}/progress", response_model=Resp[BatchProgressResp], summary="批次进度（2s 轮询）"
)
def get_progress(
    db: SessionDep,
    batch_id: int,
    after_log_id: int | None = Query(None, description="增量日志起点 id"),
) -> dict:
    """进度卡 + 活跃任务步骤 + 增量日志。"""
    return ok(batch_service.progress(db, batch_id, after_log_id))


@router.post("/{batch_id}/pause", response_model=Resp[BatchStatusResp], summary="暂停批次")
def pause_batch(db: SessionDep, batch_id: int) -> dict:
    """请求暂停（不杀线程，任务在原子步骤后回退 pending）。"""
    return ok(batch_service.pause(db, batch_id))


@router.post("/{batch_id}/resume", response_model=Resp[BatchStatusResp], summary="恢复批次")
def resume_batch(db: SessionDep, batch_id: int) -> dict:
    """恢复批次（从 pending 继续，已完成任务不重复执行）。"""
    return ok(batch_service.resume(db, batch_id))


@router.post(
    "/{batch_id}/retry-failed", response_model=Resp[SubmittedResp], summary="重试全部失败任务"
)
def retry_failed(db: SessionDep, batch_id: int) -> dict:
    """返回 ``{submitted:n}``；无可重试任务返回 3006。"""
    return ok(SubmittedResp(submitted=batch_service.retry_failed(db, batch_id)))


@router.get("/{batch_id}/logs", response_model=Resp[BatchLogsResp], summary="批次日志")
def get_logs(
    db: SessionDep,
    batch_id: int,
    level: str | None = Query(None, description="INFO | WARN | ERROR"),
    keyword: str | None = Query(None),
    after_id: int | None = Query(None),
    page_size: int = Query(200, ge=1, le=1000, alias="pageSize"),
) -> dict:
    """支持级别/关键字过滤与增量拉取。"""
    return ok(
        batch_service.logs(
            db, batch_id, level=level, keyword=keyword, after_id=after_id, page_size=page_size
        )
    )
