"""产物服务：5 条件筛选、文件存在性判定、打开目录、重新下载、删除。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.common.timeutil import add_days_iso, parse_iso, to_iso
from app.config import E
from app.db.models import Artifact, CrawlTask
from app.engine.crawler_engine import get_engine
from app.schemas.artifact import ArtifactDetail, ArtifactItem, OpenDirResp, RedownloadResp

logger = get_logger(__name__)


def _exists(path: str) -> bool:
    """产物路径是否存在（图片产物为目录）。"""
    if not path:
        return False
    try:
        return Path(path).exists()
    except OSError:  # pragma: no cover - 非法路径
        return False


def _to_item(artifact: Artifact) -> ArtifactItem:
    """ORM → 列表项。"""
    return ArtifactItem(
        id=int(artifact.id),
        task_id=int(artifact.task_id),
        data_source_id=int(artifact.data_source_id),
        data_source_name=str(artifact.data_source_name),
        type=str(artifact.type),
        name=str(artifact.name),
        category=artifact.category,
        path=str(artifact.path or ""),
        size=int(artifact.size or 0),
        status=str(artifact.status),
        is_file_exists=_exists(str(artifact.path or "")),
        created_at=artifact.created_at,
    )


def get_entity(db: Session, artifact_id: int) -> Artifact:
    """按 id 取产物，不存在抛 4004。"""
    artifact = db.get(Artifact, int(artifact_id))
    if artifact is None:
        raise BizError(ErrCode.ARTIFACT_NOT_FOUND)
    return artifact


def list_artifacts(
    db: Session,
    *,
    data_source_id: int | None = None,
    art_type: str | None = None,
    name: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[ArtifactItem], int]:
    """产物 5 条件组合筛选（数据源/类型/名称/日期区间/状态）。"""
    conditions: list[Any] = []
    if data_source_id is not None:
        conditions.append(Artifact.data_source_id == int(data_source_id))
    if art_type and art_type in E.ARTIFACT_TYPES:
        conditions.append(Artifact.type == art_type)
    if name:
        conditions.append(Artifact.name.like(f"%{name.strip()}%"))
    if date_from:
        start = parse_iso(date_from)
        if start is not None:
            conditions.append(Artifact.created_at >= (to_iso(start) or date_from))
    if date_to:
        end = parse_iso(date_to)
        if end is not None:
            conditions.append(Artifact.created_at <= (add_days_iso(end, 1) or date_to))
    if status and status in E.ARTIFACT_STATUSES:
        conditions.append(Artifact.status == status)

    total = int(
        db.execute(select(func.count(Artifact.id)).where(*conditions)).scalar() or 0
    )
    rows = db.execute(
        select(Artifact)
        .where(*conditions)
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).scalars().all()
    return [_to_item(artifact) for artifact in rows], total


def get_detail(db: Session, artifact_id: int) -> ArtifactDetail:
    """产物详情（含失败原因与文件缺失判定）。"""
    artifact = get_entity(db, artifact_id)
    return ArtifactDetail(
        id=int(artifact.id),
        task_id=int(artifact.task_id),
        task_result_id=artifact.task_result_id,
        data_source_id=int(artifact.data_source_id),
        data_source_name=str(artifact.data_source_name),
        type=str(artifact.type),
        name=str(artifact.name),
        category=artifact.category,
        path=str(artifact.path or ""),
        size=int(artifact.size or 0),
        status=str(artifact.status),
        error_msg=artifact.error_msg,
        is_file_exists=_exists(str(artifact.path or "")),
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
    )


def open_dir(db: Session, artifact_id: int) -> OpenDirResp:
    """打开所在目录（服务端唤起文件管理器，失败降级返回路径）。"""
    artifact = get_entity(db, artifact_id)
    raw_path = str(artifact.path or "")
    if not raw_path or not _exists(raw_path):
        raise BizError(ErrCode.ARTIFACT_NOT_FOUND, "产物文件不存在或已被移动")
    target = Path(raw_path)
    directory = target if target.is_dir() else target.parent
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(directory))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(directory)], check=False)  # noqa: S603,S607
        else:
            subprocess.run(["xdg-open", str(directory)], check=False)  # noqa: S603,S607
    except OSError as exc:
        logger.warning("打开目录失败：%s（%s）", directory, exc)
        return OpenDirResp(opened=False, path=str(directory))
    return OpenDirResp(opened=True, path=str(directory))


def redownload(db: Session, artifact_id: int) -> RedownloadResp:
    """重新下载（仅失败产物可用，复用原任务记录回到 pending）。"""
    artifact = get_entity(db, artifact_id)
    task = db.get(CrawlTask, int(artifact.task_id))
    if task is None:
        raise BizError(ErrCode.TASK_NOT_FOUND, "产物对应的任务已不存在")
    if task.status == E.TASK_RUNNING:
        raise BizError(ErrCode.TASK_NOT_RETRYABLE, "任务正在执行中，请稍后再试")
    if task.status != E.TASK_FAILED:
        raise BizError(
            ErrCode.TASK_NOT_RETRYABLE,
            f"仅失败产物可重新下载（当前任务状态 {task.status}）",
        )
    submitted = get_engine().retry_tasks([int(task.id)])
    if submitted == 0:
        raise BizError(ErrCode.TASK_NOT_RETRYABLE, "任务无法重新下载")
    return RedownloadResp(task_id=int(task.id), status=E.TASK_PENDING)


def delete(db: Session, artifact_id: int, delete_file: bool = True) -> int:
    """删除产物记录（可选同时删除磁盘文件）。"""
    artifact = get_entity(db, artifact_id)
    raw_path = str(artifact.path or "")
    db.delete(artifact)
    db.commit()
    if delete_file and raw_path:
        target = Path(raw_path)
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        except OSError as exc:
            logger.warning("删除产物文件失败：%s（%s）", raw_path, exc)
    logger.info("删除产物 #%s（delete_file=%s）", artifact_id, delete_file)
    return 1
