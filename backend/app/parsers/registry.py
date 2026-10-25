"""解析器注册表：脚本优先，否则按 type 选择内置解析器。

自定义脚本契约（脚本入口示例）::

    def parse(args):
        # args = {"mode": "list"|"detail", "url": str, "page": int,
        #         "item": {"title":..., "url":..., "payload":...}, "config": {...}}
        if args["mode"] == "list":
            html = http_get(args["url"])
            return {"items": [{"title": ..., "url": ..., "date": "2026-10-25"}],
                    "pages": 12}
        html = http_get(args["url"])
        return {"title": ..., "content": ..., "images": [...], "video": "https://x/a.m3u8"}
"""

from __future__ import annotations

from typing import Any

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.config import E
from app.downloader.http_client import HttpClient
from app.engine.script_sandbox import ScriptSandbox
from app.parsers.base import BaseParser, DetailResult, ListItem, normalize_date
from app.parsers.html_list_parser import HtmlListParser
from app.parsers.image_set_parser import ImageSetParser

logger = get_logger(__name__)


class ScriptedParser(BaseParser):
    """把自定义脚本适配成 BaseParser 接口。"""

    name = "scripted"

    def __init__(self, ds: Any, http: HttpClient | None = None) -> None:
        super().__init__(ds, http)
        self.sandbox = ScriptSandbox(http=self.http)
        self._last_pages: int | None = None
        self._page_size: int | None = None

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------
    def parse_list(self, url: str, page: int = 1) -> list[ListItem]:
        """调用脚本 list 模式，返回标准化 ListItem 列表。"""
        page_url = self.build_url(url, page)
        data = self.sandbox.execute(
            self._script(),
            self._entry(),
            {
                "mode": "list",
                "url": page_url,
                "page": int(page),
                "config": self.config,
            },
        )
        raw_items = data.get("items") or []
        pages = data.get("pages")
        if isinstance(pages, int):
            self._last_pages = max(0, pages)
        if not isinstance(raw_items, list):
            raise BizError(
                ErrCode.SCRIPT_ERROR, "脚本 list 模式必须返回 items 数组", retryable=False
            )

        items: list[ListItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            link = str(raw.get("url") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not link or not title:
                continue
            payload = dict(raw.get("payload") or {})
            for key in ("date", "chapter_index", "book", "novel", "extra"):
                if key in raw and raw[key] is not None:
                    payload.setdefault(key, raw[key])
            items.append(
                ListItem(
                    title=title,
                    url=self.absolute(link, page_url),
                    seq_no=0,
                    date=normalize_date(raw.get("date")) or normalize_date(str(payload.get("date") or "")),
                    payload=payload,
                )
            )

        if items and self._page_size is None:
            self._page_size = len(items)
        for offset, item in enumerate(items):
            explicit = item.payload.get("seq_no")
            if explicit is not None:
                try:
                    item.seq_no = int(explicit)
                    continue
                except (TypeError, ValueError):
                    pass
            base = (max(1, int(page)) - 1) * (self._page_size or len(items) or 0)
            item.seq_no = base + offset + 1
        return self.require_items(items, page_url)

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def parse_detail(self, item: ListItem) -> DetailResult:
        """调用脚本 detail 模式，返回正文 / 图片 / 视频地址。"""
        data = self.sandbox.execute(
            self._script(),
            self._entry(),
            {
                "mode": "detail",
                "url": item.url,
                "page": 1,
                "item": {
                    "title": item.title,
                    "url": item.url,
                    "date": item.date,
                    "payload": item.payload,
                },
                "config": self.config,
            },
        )
        images = [
            self.absolute(src, item.url)
            for src in (data.get("images") or [])
            if str(src).strip()
        ]
        video = data.get("video") or data.get("video_url")
        return DetailResult(
            title=str(data.get("title") or item.title),
            content=str(data.get("content") or ""),
            images=images,
            video_url=self.absolute(str(video), item.url) if video else None,
            extra=dict(data.get("extra") or {}),
        )

    def parse_pages(self, url: str) -> int | None:
        """脚本在 list 模式返回的 ``pages``（未返回则视作未知）。"""
        return self._last_pages

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _script(self) -> str:
        return str(getattr(self.ds, "script", "") or "")

    def _entry(self) -> str:
        return str(getattr(self.ds, "script_entry", "parse") or "parse")


def build_parser(ds: Any, http: HttpClient | None = None) -> BaseParser:
    """按数据源配置构建解析器：脚本优先，否则按 type 选内置解析器。"""
    if str(getattr(ds, "script", "") or "").strip():
        return ScriptedParser(ds, http)
    ds_type = str(getattr(ds, "type", ""))
    if ds_type == E.TYPE_IMAGE:
        return ImageSetParser(ds, http)
    if ds_type == E.TYPE_VIDEO:
        return HtmlListParser(ds, http)
    return HtmlListParser(ds, http)


__all__ = ["ScriptedParser", "build_parser"]
