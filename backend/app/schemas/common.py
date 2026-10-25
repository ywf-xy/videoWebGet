"""统一响应体与通用 DTO（ARCHITECTURE §11.2）。

响应体固定 ``{"code":0,"data":...,"message":"ok"}``；分页负载固定
``{"items":[],"total":0,"page":1,"pageSize":10}``。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.common.errors import ErrCode, message_for

DataT = TypeVar("DataT")


class CamelModel(BaseModel):
    """全站 DTO 基类。

    说明：虽然命名为 CamelModel（沿用架构文档），但字段一律保持 **snake_case**
    （ARCHITECTURE §11.1：JSON 出入参不转驼峰），仅分页信封使用 ``pageSize``。
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        protected_namespaces=(),
    )


class Resp(CamelModel, Generic[DataT]):
    """统一响应信封。"""

    code: int = 0
    data: DataT | None = None
    message: str = "ok"


class PagePayload(CamelModel, Generic[DataT]):
    """分页负载。"""

    items: list[DataT] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    pageSize: int = 10


class IdResp(CamelModel):
    """通用 id 返回。"""

    id: int


class DeletedResp(CamelModel):
    """通用删除返回。"""

    deleted: int = 1


class SubmittedResp(CamelModel):
    """批量提交条数。"""

    submitted: int = 0


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """构造成功响应体。"""
    return {"code": int(ErrCode.OK), "data": data, "message": message}


def fail(code: int, message: str | None = None) -> dict[str, Any]:
    """构造失败响应体（data 恒为 None）。"""
    return {"code": int(code), "data": None, "message": message or message_for(int(code))}


def page_payload(
    items: list[Any], total: int, page: int = 1, page_size: int = 10
) -> dict[str, Any]:
    """构造分页响应体（键名与前端契约一致）。"""
    return {
        "items": items,
        "total": int(total),
        "page": int(page),
        "pageSize": int(page_size),
    }


def validate_http_url(value: str) -> str:
    """校验 http/https URL 格式（返回原值，失败抛 ValueError）。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError("地址不能为空")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise ValueError("地址必须以 http:// 或 https:// 开头")
    if not parts.netloc:
        raise ValueError("地址缺少域名")
    return text


__all__ = [
    "CamelModel",
    "DeletedResp",
    "IdResp",
    "PagePayload",
    "Resp",
    "SubmittedResp",
    "fail",
    "ok",
    "page_payload",
    "validate_http_url",
]
