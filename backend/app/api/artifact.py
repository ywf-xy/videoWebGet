"""产物 API：5 条件筛选 / 详情 / 打开目录 / 重新下载 / 删除。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import PageDep, SessionDep
from app.schemas.artifact import ArtifactDetail, ArtifactItem, OpenDirResp, RedownloadResp
from app.schemas.common import DeletedResp, PagePayload, Resp, ok
from app.services import artifact_service

router = APIRouter(prefix="/artifacts", tags=["artifact"])


@router.get("", response_model=Resp[PagePayload[ArtifactItem]], summary="产物列表")
def list_artifacts(
    db: SessionDep,
    page: PageDep,
    data_source_id: int | None = Query(None),
    type: str | None = Query(None, description="video | text | pdf | image"),
    name: str | None = Query(None, description="名称模糊匹配"),
    date_from: str | None = Query(None, description="yyyy-MM-dd"),
    date_to: str | None = Query(None, description="yyyy-MM-dd"),
    status: str | None = Query(None, description="processing | success | failed | missing"),
) -> dict:
    """五条件组合筛选，按创建时间倒序；含 is_file_exists 判定。"""
    items, total = artifact_service.list_artifacts(
        db,
        data_source_id=data_source_id,
        art_type=type,
        name=name,
        date_from=date_from,
        date_to=date_to,
        status=status,
        page=page.page,
        page_size=page.page_size,
    )
    return ok(
        PagePayload[ArtifactItem](
            items=items, total=total, page=page.page, pageSize=page.page_size
        )
    )


@router.get("/{artifact_id}", response_model=Resp[ArtifactDetail], summary="产物详情")
def get_artifact(db: SessionDep, artifact_id: int) -> dict:
    """含失败原因与文件缺失判定。"""
    return ok(artifact_service.get_detail(db, artifact_id))


@router.post(
    "/{artifact_id}/open-dir", response_model=Resp[OpenDirResp], summary="打开所在目录"
)
def open_artifact_dir(db: SessionDep, artifact_id: int) -> dict:
    """服务端唤起文件管理器；失败降级返回 path（前端提示「路径已复制」）。"""
    return ok(artifact_service.open_dir(db, artifact_id))


@router.post(
    "/{artifact_id}/redownload", response_model=Resp[RedownloadResp], summary="重新下载"
)
def redownload_artifact(db: SessionDep, artifact_id: int) -> dict:
    """复用原任务记录重新入队。"""
    return ok(artifact_service.redownload(db, artifact_id))


@router.delete("/{artifact_id}", response_model=Resp[DeletedResp], summary="删除产物")
def delete_artifact(
    db: SessionDep,
    artifact_id: int,
    delete_file: bool = Query(True, description="是否同时删除磁盘文件"),
) -> dict:
    """删除产物记录（可选删除文件）。"""
    return ok(DeletedResp(deleted=artifact_service.delete(db, artifact_id, delete_file)))
