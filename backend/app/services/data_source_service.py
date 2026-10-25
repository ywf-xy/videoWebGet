"""数据源服务：CRUD、启停、导入导出、脚本校验/试运行、健康度读取。"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.common.timeutil import now_iso
from app.config import E
from app.db.models import CrawlBatch, DataSource
from app.engine.script_sandbox import ScriptSandbox
from app.schemas.data_source import (
    DataSourceCreate,
    DataSourceDetail,
    DataSourceExportItem,
    DataSourceItem,
    DataSourceUpdate,
    ImportResultResp,
    ImportRowResult,
    ScriptTestPayload,
    ScriptTestResp,
    ScriptValidatePayload,
    ScriptValidateResp,
)
from app.services import health_service

logger = get_logger(__name__)


def _to_item(ds: DataSource) -> DataSourceItem:
    """ORM → 列表项。"""
    return DataSourceItem(
        id=int(ds.id),
        name=str(ds.name),
        type=str(ds.type),
        category=ds.category,
        homepage_url=str(ds.homepage_url),
        alt_urls_count=len(ds.alt_urls or []),
        health_score=ds.health_score,
        last_crawled_at=ds.last_crawled_at,
        total_items=int(ds.total_items or 0),
        enabled=bool(ds.enabled),
        has_script=bool(str(ds.script or "").strip()),
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


def _to_detail(ds: DataSource) -> DataSourceDetail:
    """ORM → 详情。"""
    return DataSourceDetail(
        id=int(ds.id),
        name=str(ds.name),
        type=str(ds.type),
        category=ds.category,
        homepage_url=str(ds.homepage_url),
        alt_urls=list(ds.alt_urls or []),
        current_url=ds.current_url,
        script=ds.script,
        script_entry=str(ds.script_entry or "parse"),
        config_json=dict(ds.config_json or {}),
        is_novel=bool(ds.is_novel),
        enabled=bool(ds.enabled),
        health_score=ds.health_score,
        success_rate_20=ds.success_rate_20,
        last_success_at=ds.last_success_at,
        last_crawled_at=ds.last_crawled_at,
        total_items=int(ds.total_items or 0),
        cursor_last_item_no=int(ds.cursor_last_item_no or 0),
        cursor_last_page=int(ds.cursor_last_page or 0),
        cursor_last_success_date=ds.cursor_last_success_date,
        notes=ds.notes,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def list_data_sources(
    db: Session,
    *,
    ds_type: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[DataSourceItem], int]:
    """分页查询数据源（关键字命中名称或地址）。"""
    conditions = [DataSource.is_deleted == 0]
    if ds_type and ds_type in E.TYPES:
        conditions.append(DataSource.type == ds_type)
    if category:
        conditions.append(DataSource.category == category)
    if enabled is not None:
        conditions.append(DataSource.enabled == (1 if enabled else 0))
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(or_(DataSource.name.like(like), DataSource.homepage_url.like(like)))

    total = int(
        db.execute(select(func.count(DataSource.id)).where(*conditions)).scalar() or 0
    )
    rows = (
        db.execute(
            select(DataSource)
            .where(*conditions)
            .order_by(DataSource.updated_at.desc(), DataSource.id.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return [_to_item(ds) for ds in rows], total


def get_entity(db: Session, ds_id: int) -> DataSource:
    """按 id 取未删除的数据源，不存在抛 2001。"""
    ds = db.get(DataSource, int(ds_id))
    if ds is None or int(ds.is_deleted) == 1:
        raise BizError(ErrCode.DS_NOT_FOUND)
    return ds


def get_detail(db: Session, ds_id: int) -> DataSourceDetail:
    """数据源详情。"""
    return _to_detail(get_entity(db, ds_id))


def get_health(db: Session, ds_id: int):
    """数据源健康度明细。"""
    get_entity(db, ds_id)
    return health_service.get_detail(db, ds_id)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
def _assert_unique(
    db: Session, name: str, homepage_url: str, exclude_id: int | None = None
) -> None:
    """name + homepage_url 唯一性校验（仅未删除记录）。"""
    conditions = [
        DataSource.is_deleted == 0,
        DataSource.name == name,
        DataSource.homepage_url == homepage_url,
    ]
    if exclude_id is not None:
        conditions.append(DataSource.id != int(exclude_id))
    exists = db.execute(select(DataSource.id).where(*conditions).limit(1)).first()
    if exists is not None:
        raise BizError(ErrCode.DS_DUPLICATE, "同名同类地址的数据源已存在")


def create(db: Session, payload: DataSourceCreate) -> int:
    """新增数据源，返回 id。"""
    _assert_unique(db, payload.name.strip(), str(payload.homepage_url))
    ds = DataSource(
        name=payload.name.strip(),
        type=payload.type,
        category=(payload.category or None),
        homepage_url=str(payload.homepage_url),
        alt_urls=list(payload.alt_urls or []),
        current_url=payload.current_url or str(payload.homepage_url),
        script=payload.script,
        script_entry=payload.script_entry or "parse",
        config_json=dict(payload.config_json or {}),
        is_novel=1 if payload.is_novel else 0,
        enabled=1 if payload.enabled else 0,
        notes=payload.notes,
        is_deleted=0,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    logger.info("新增数据源 #%s %s（%s）", ds.id, ds.name, ds.type)
    return int(ds.id)


def update(db: Session, ds_id: int, payload: DataSourceUpdate) -> int:
    """编辑数据源（仅提交字段生效）。"""
    ds = get_entity(db, ds_id)
    data = payload.model_dump(exclude_unset=True)

    new_name = str(data.get("name") or ds.name).strip()
    new_url = str(data.get("homepage_url") or ds.homepage_url)
    if new_name != ds.name or new_url != ds.homepage_url:
        _assert_unique(db, new_name, new_url, exclude_id=int(ds.id))

    if "name" in data and data["name"] is not None:
        ds.name = new_name
    if "type" in data and data["type"] is not None:
        ds.type = str(data["type"])
    if "category" in data:
        ds.category = data["category"] or None
    if "homepage_url" in data and data["homepage_url"] is not None:
        ds.homepage_url = new_url
    if "alt_urls" in data and data["alt_urls"] is not None:
        ds.alt_urls = list(data["alt_urls"])
    if "current_url" in data:
        ds.current_url = data["current_url"] or ds.homepage_url
    if "script" in data:
        ds.script = data["script"]
    if "script_entry" in data and data["script_entry"]:
        ds.script_entry = str(data["script_entry"])
    if "config_json" in data and data["config_json"] is not None:
        ds.config_json = dict(data["config_json"])
    if "is_novel" in data and data["is_novel"] is not None:
        ds.is_novel = 1 if data["is_novel"] else 0
    if "enabled" in data and data["enabled"] is not None:
        ds.enabled = 1 if data["enabled"] else 0
    if "notes" in data:
        ds.notes = data["notes"]

    ds.updated_at = now_iso()
    db.commit()
    logger.info("更新数据源 #%s", ds.id)
    return int(ds.id)


def set_enabled(db: Session, ds_id: int, enabled: bool) -> bool:
    """启用/停用数据源。"""
    ds = get_entity(db, ds_id)
    ds.enabled = 1 if enabled else 0
    ds.updated_at = now_iso()
    db.commit()
    return bool(ds.enabled)


def delete(db: Session, ds_id: int) -> int:
    """软删除数据源（有运行中批次时拒绝）。"""
    ds = get_entity(db, ds_id)
    busy = db.execute(
        select(CrawlBatch.id)
        .where(
            CrawlBatch.data_source_id == int(ds.id),
            CrawlBatch.status.in_(E.BATCH_BUSY_STATUSES),
        )
        .limit(1)
    ).first()
    if busy is not None:
        raise BizError(ErrCode.DS_BUSY, "该数据源有运行中的批次，请先暂停或等待完成")
    ds.is_deleted = 1
    ds.enabled = 0
    ds.updated_at = now_iso()
    db.commit()
    logger.info("软删除数据源 #%s", ds.id)
    return 1


# ---------------------------------------------------------------------------
# 脚本
# ---------------------------------------------------------------------------
def validate_script(db: Session, ds_id: int, payload: ScriptValidatePayload) -> ScriptValidateResp:
    """脚本语法校验（返回行号列号）。"""
    get_entity(db, ds_id)
    result = ScriptSandbox().validate(payload.script, payload.entry)
    return ScriptValidateResp(
        valid=result.valid,
        line=result.line,
        column=result.column,
        message=result.message,
    )


def test_script(db: Session, ds_id: int, payload: ScriptTestPayload) -> ScriptTestResp:
    """脚本试运行（对指定网址解析列表，回显前 5 条）。"""
    ds = get_entity(db, ds_id)
    sandbox = ScriptSandbox()
    check = sandbox.validate(payload.script, payload.entry)
    if not check.valid:
        raise BizError(
            ErrCode.SCRIPT_ERROR, check.message, retryable=False, detail=f"line={check.line}"
        )
    data = sandbox.execute(
        payload.script,
        payload.entry,
        {
            "mode": "list",
            "url": payload.url,
            "page": 1,
            "config": dict(ds.config_json or {}),
        },
    )
    items = data.get("items") or []
    if not isinstance(items, list):
        raise BizError(ErrCode.SCRIPT_ERROR, "脚本必须返回 items 数组", retryable=False)
    samples: list[dict[str, Any]] = [item for item in items[:5] if isinstance(item, dict)]
    fields: list[str] = []
    for sample in samples:
        for key in sample:
            if key not in fields:
                fields.append(str(key))
    return ScriptTestResp(count=len(items), fields=fields, samples=samples)


# ---------------------------------------------------------------------------
# 导入 / 导出
# ---------------------------------------------------------------------------
_IMPORT_FIELDS: Sequence[str] = (
    "name",
    "type",
    "category",
    "homepage_url",
    "alt_urls",
    "script",
    "script_entry",
    "config_json",
    "is_novel",
    "enabled",
    "notes",
)


def _parse_bool(value: Any, default: bool = False) -> bool:
    """兼容 1/0、true/false、是/否。"""
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "y", "是"):
        return True
    if text in ("0", "false", "no", "n", "否"):
        return False
    return default


def _normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    """导入行标准化（CSV 的 alt_urls 用竖线分隔，config_json 为 JSON 字符串）。"""
    row: dict[str, Any] = {}
    for key in _IMPORT_FIELDS:
        if key in raw:
            row[key] = raw[key]
    alt = row.get("alt_urls")
    if isinstance(alt, str):
        row["alt_urls"] = [part.strip() for part in alt.split("|") if part.strip()]
    config = row.get("config_json")
    if isinstance(config, str):
        try:
            row["config_json"] = json.loads(config) if config.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"config_json 不是合法 JSON：{exc}") from exc
    if "is_novel" in row:
        row["is_novel"] = _parse_bool(row["is_novel"], False)
    if "enabled" in row:
        row["enabled"] = _parse_bool(row["enabled"], True)
    return row


def _read_import_rows(content: bytes, filename: str) -> list[dict[str, Any]]:
    """按扩展名解析导入文件（JSON 数组 / CSV）。"""
    suffix = str(filename or "").lower().rsplit(".", 1)[-1] if "." in str(filename or "") else ""
    text = content.decode("utf-8-sig", errors="replace")
    if suffix == "csv":
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict[str, Any]] = []
        for raw in reader:
            rows.append({str(k).strip(): v for k, v in raw.items() if k is not None})
        return rows
    if suffix in ("json", ""):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BizError(ErrCode.FILE_FORMAT, f"JSON 解析失败：{exc}") from exc
        if isinstance(parsed, dict):
            for key in ("items", "data", "list"):
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break
        if not isinstance(parsed, list):
            raise BizError(ErrCode.FILE_FORMAT, "JSON 顶层必须是数组")
        return [row for row in parsed if isinstance(row, dict)]
    raise BizError(ErrCode.FILE_FORMAT, "仅支持 .json / .csv 文件")


def import_rows(
    db: Session, content: bytes, filename: str, overwrite: bool = False
) -> ImportResultResp:
    """批量导入（逐行结果；``overwrite=False`` 时跳过重复）。"""
    rows = _read_import_rows(content, filename)
    if not rows:
        raise BizError(ErrCode.FILE_FORMAT, "文件中没有可导入的数据行")

    success = 0
    failed = 0
    results: list[ImportRowResult] = []
    for index, raw in enumerate(rows, start=1):
        try:
            normalized = _normalize_row(raw)
            candidate = DataSourceCreate(**normalized)
        except ValidationError as exc:
            failed += 1
            first = exc.errors()[0] if exc.errors() else {}
            reason = f"{'.'.join(str(p) for p in first.get('loc', ()))}: {first.get('msg', '字段校验失败')}"
            results.append(ImportRowResult(line=index, status="failed", reason=reason))
            continue
        except ValueError as exc:
            failed += 1
            results.append(ImportRowResult(line=index, status="failed", reason=str(exc)))
            continue

        existing = db.execute(
            select(DataSource)
            .where(
                DataSource.is_deleted == 0,
                DataSource.name == candidate.name.strip(),
                DataSource.homepage_url == str(candidate.homepage_url),
            )
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None and not overwrite:
            results.append(
                ImportRowResult(line=index, status="skipped", reason="同 name+homepage_url 已存在")
            )
            continue
        try:
            if existing is not None:
                update(
                    db,
                    int(existing.id),
                    DataSourceUpdate(**candidate.model_dump(exclude={"type"})),
                )
                results.append(ImportRowResult(line=index, status="success", reason="已覆盖"))
            else:
                create(db, candidate)
                results.append(ImportRowResult(line=index, status="success"))
            success += 1
        except BizError as exc:
            failed += 1
            results.append(ImportRowResult(line=index, status="failed", reason=exc.message))
    logger.info("导入完成：成功 %s / 失败 %s / 共 %s 行", success, failed, len(rows))
    return ImportResultResp(success=success, failed=failed, rows=results)


def export_items(
    db: Session,
    *,
    scope: str = "all",
    ids: list[int] | None = None,
    ds_type: str | None = None,
) -> list[dict[str, Any]]:
    """导出数据源（UTF-8 JSON 数组，字段与导入往返一致）。"""
    conditions = [DataSource.is_deleted == 0]
    if scope == "selected":
        if not ids:
            raise BizError(ErrCode.PARAM_INVALID, "请选择要导出的数据源")
        conditions.append(DataSource.id.in_([int(item) for item in ids]))
    elif scope == "type":
        if not ds_type or ds_type not in E.TYPES:
            raise BizError(ErrCode.PARAM_INVALID, "请指定要导出的类型")
        conditions.append(DataSource.type == ds_type)
    rows = db.execute(select(DataSource).where(*conditions).order_by(DataSource.id.asc())).scalars().all()
    return [
        DataSourceExportItem(
            name=str(ds.name),
            type=str(ds.type),
            category=ds.category,
            homepage_url=str(ds.homepage_url),
            alt_urls=list(ds.alt_urls or []),
            script=ds.script,
            script_entry=str(ds.script_entry or "parse"),
            config_json=dict(ds.config_json or {}),
            is_novel=bool(ds.is_novel),
            enabled=bool(ds.enabled),
            notes=ds.notes,
        ).model_dump()
        for ds in rows
    ]


def template_rows() -> list[dict[str, Any]]:
    """导入模板（含一个视频示例）。"""
    return [
        {
            "name": "示例影视站",
            "type": "video",
            "category": "科幻",
            "homepage_url": "https://example.com/videos",
            "alt_urls": ["https://example.org/videos"],
            "script": None,
            "script_entry": "parse",
            "config_json": {
                "list_url": "https://example.com/videos?page={page}",
                "item_selector": ".list li",
                "link_selector": "a@href",
                "title_selector": "a@text",
                "detail_video_selector": "video@src",
                "page_param": "page",
                "max_pages": 50,
            },
            "is_novel": False,
            "enabled": True,
            "notes": "导入模板示例，可直接修改后导入",
        }
    ]
