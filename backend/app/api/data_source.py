"""数据源 API：CRUD / 启停 / 导入导出 / 健康度 / 脚本校验与试运行。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from app.api.deps import PageDep, SessionDep
from app.common.errors import BizError, ErrCode
from app.schemas.common import (
    DeletedResp,
    IdResp,
    PagePayload,
    Resp,
    ok,
)
from app.schemas.data_source import (
    DataSourceCreate,
    DataSourceDetail,
    DataSourceItem,
    DataSourceUpdate,
    EnabledPayload,
    EnabledResp,
    HealthResp,
    ImportResultResp,
    ScriptTestPayload,
    ScriptTestResp,
    ScriptValidatePayload,
    ScriptValidateResp,
)
from app.services import data_source_service

router = APIRouter(prefix="/data-sources", tags=["data-source"])

#: 导入文件大小上限（10MB）
MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.get("", response_model=Resp[PagePayload[DataSourceItem]], summary="数据源列表")
def list_data_sources(
    db: SessionDep,
    page: PageDep,
    type: str | None = Query(None, description="video | text | image"),
    keyword: str | None = Query(None, description="名称或地址关键字"),
    category: str | None = Query(None),
    enabled: bool | None = Query(None),
) -> dict:
    """分页查询数据源（只返回未删除记录）。"""
    items, total = data_source_service.list_data_sources(
        db,
        ds_type=type,
        keyword=keyword,
        category=category,
        enabled=enabled,
        page=page.page,
        page_size=page.page_size,
    )
    return ok(PagePayload[DataSourceItem](items=items, total=total, page=page.page, pageSize=page.page_size))


@router.get("/template", summary="导入模板（JSON 附件）")
def download_template() -> Response:
    """返回导入模板 JSON（UTF-8）。"""
    payload = json.dumps(data_source_service.template_rows(), ensure_ascii=False, indent=2)
    return Response(
        content=payload.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="crawlerhub-data-source-template.json"'},
    )


@router.get("/export", summary="导出数据源（JSON 附件）")
def export_data_sources(
    db: SessionDep,
    scope: str = Query("all", description="all | selected | type"),
    ids: str | None = Query(None, description="逗号分隔的数据源 id（scope=selected）"),
    type: str | None = Query(None, description="video | text | image（scope=type）"),
) -> Response:
    """导出 UTF-8 JSON 数组，可直接被导入接口回读。"""
    id_list: list[int] = []
    if ids:
        for chunk in str(ids).split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                id_list.append(int(chunk))
            except ValueError as exc:
                raise BizError(ErrCode.PARAM_INVALID, f"非法的数据源 id：{chunk}") from exc
    rows: list[dict[str, Any]] = data_source_service.export_items(
        db, scope=scope, ids=id_list, ds_type=type
    )
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    return Response(
        content=payload.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="crawlerhub-data-sources.json"'},
    )


@router.post("/import", response_model=Resp[ImportResultResp], summary="导入数据源")
async def import_data_sources(
    db: SessionDep,
    file: UploadFile = File(..., description=".json / .csv"),
    overwrite: bool = Form(False, description="是否覆盖同 name+homepage_url 的记录"),
) -> dict:
    """批量导入，返回逐行结果（成功/跳过/失败 + 原因）。"""
    content = await file.read()
    if not content:
        raise BizError(ErrCode.FILE_FORMAT, "上传文件为空")
    if len(content) > MAX_IMPORT_BYTES:
        raise BizError(ErrCode.FILE_TOO_LARGE, "导入文件不能超过 10MB")
    result = data_source_service.import_rows(
        db, content, file.filename or "import.json", overwrite=overwrite
    )
    return ok(result)


@router.post("", response_model=Resp[IdResp], summary="新增数据源")
def create_data_source(db: SessionDep, payload: DataSourceCreate) -> dict:
    """新增数据源（name + homepage_url 冲突返回 2002）。"""
    ds_id = data_source_service.create(db, payload)
    return ok(IdResp(id=ds_id))


@router.get("/{ds_id}", response_model=Resp[DataSourceDetail], summary="数据源详情")
def get_data_source(db: SessionDep, ds_id: int) -> dict:
    """详情含脚本全文、config_json 与游标三字段。"""
    return ok(data_source_service.get_detail(db, ds_id))


@router.put("/{ds_id}", response_model=Resp[IdResp], summary="编辑数据源")
def update_data_source(db: SessionDep, ds_id: int, payload: DataSourceUpdate) -> dict:
    """编辑数据源（仅提交字段生效）。"""
    return ok(IdResp(id=data_source_service.update(db, ds_id, payload)))


@router.patch("/{ds_id}/enabled", response_model=Resp[EnabledResp], summary="启用/停用")
def toggle_data_source(db: SessionDep, ds_id: int, payload: EnabledPayload) -> dict:
    """启用或停用数据源。"""
    enabled = data_source_service.set_enabled(db, ds_id, payload.enabled)
    return ok(EnabledResp(enabled=enabled))


@router.delete("/{ds_id}", response_model=Resp[DeletedResp], summary="删除数据源（软删除）")
def delete_data_source(db: SessionDep, ds_id: int) -> dict:
    """软删除；存在运行中批次时返回 2003。"""
    return ok(DeletedResp(deleted=data_source_service.delete(db, ds_id)))


@router.get("/{ds_id}/health", response_model=Resp[HealthResp], summary="数据源健康度")
def get_data_source_health(db: SessionDep, ds_id: int) -> dict:
    """健康分 / 近 20 次成功率 / 最近成功时间 / 样本量。"""
    return ok(data_source_service.get_health(db, ds_id))


@router.post(
    "/{ds_id}/script/validate",
    response_model=Resp[ScriptValidateResp],
    summary="脚本语法校验",
)
def validate_script(
    db: SessionDep, ds_id: int, payload: ScriptValidatePayload
) -> dict:
    """返回 ``{valid,line,column,message}``。"""
    return ok(data_source_service.validate_script(db, ds_id, payload))


@router.post(
    "/{ds_id}/script/test",
    response_model=Resp[ScriptTestResp],
    summary="脚本试运行（回显前 5 条）",
)
def test_script(db: SessionDep, ds_id: int, payload: ScriptTestPayload) -> dict:
    """对指定网址试运行脚本，返回条数/字段名/样例。"""
    return ok(data_source_service.test_script(db, ds_id, payload))
