"""API 依赖：数据库会话、分页参数。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db.base import get_db


def get_db_session() -> Iterator[Session]:
    """请求级会话（事务提交由 services 层负责）。"""
    yield from get_db()


SessionDep = Annotated[Session, Depends(get_db_session)]


class PageParams:
    """分页参数（查询串使用 ``page`` / ``pageSize``）。"""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 起"),
        page_size: int = Query(10, ge=1, le=200, alias="pageSize", description="每页条数"),
    ) -> None:
        self.page: int = int(page)
        self.page_size: int = int(page_size)

    @property
    def offset(self) -> int:
        """SQL offset。"""
        return (self.page - 1) * self.page_size


PageDep = Annotated[PageParams, Depends(PageParams)]
