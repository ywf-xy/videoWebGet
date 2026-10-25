"""内置 HTML 列表解析器（依靠 config_json 的 CSS 选择器适配站点）。

config_json 支持的键见 ARCHITECTURE §3.1；额外支持：
- ``total_pages`` / ``total_pages_selector`` / ``total_pages_regex``（S2 总页数）
- ``seq_no_selector``（列表页自带序号时优先使用）
"""

from __future__ import annotations

import re
from typing import Any, Final

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.parsers.base import BaseParser, DetailResult, ListItem, normalize_date

logger = get_logger(__name__)

#: 默认选择器（config_json 未配置时的兜底）
DEFAULT_ITEM_SELECTOR: Final[str] = "li"
DEFAULT_LINK_SELECTOR: Final[str] = "a@href"
DEFAULT_TITLE_SELECTOR: Final[str] = "a@text"


class HtmlListParser(BaseParser):
    """通用 HTML 列表 + 详情解析器。"""

    name = "html_list"

    def __init__(self, ds: Any, http: Any = None) -> None:
        super().__init__(ds, http)
        # 首屏条目数用于推算跨页全局序号（S1 游标依赖 seq_no 稳定性）
        self._page_size: int | None = None

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------
    def parse_list(self, url: str, page: int = 1) -> list[ListItem]:
        """解析一页列表，并按「(页码-1) × 每页条数」推算全局序号。"""
        page_url = self.build_url(url, page)
        soup = self.fetch_soup(page_url)
        item_selector = str(self.cfg("item_selector", DEFAULT_ITEM_SELECTOR))
        link_selector = str(self.cfg("link_selector", DEFAULT_LINK_SELECTOR))
        title_selector = str(self.cfg("title_selector", DEFAULT_TITLE_SELECTOR))
        date_selector = self.cfg("date_selector", None)
        seq_selector = self.cfg("seq_no_selector", None)

        rows = soup.select(item_selector)
        items: list[ListItem] = []
        for row in rows:
            link = self.extract(row, link_selector)
            title = self.extract(row, title_selector) or self.node_text(row)
            if not link or not title:
                continue
            raw_date = self.extract(row, date_selector) if date_selector else ""
            date_value = normalize_date(raw_date)
            payload: dict[str, Any] = {}
            if raw_date:
                payload["raw_date"] = raw_date
            if seq_selector:
                explicit = self.extract(row, str(seq_selector))
                digits = re.sub(r"\D", "", explicit)
                if digits:
                    payload["seq_no"] = int(digits)
            items.append(
                ListItem(
                    title=title,
                    url=self.absolute(link, page_url),
                    seq_no=0,
                    date=date_value,
                    payload=payload,
                )
            )

        if items and self._page_size is None:
            self._page_size = len(items)
        for offset, item in enumerate(items):
            if "seq_no" not in item.payload:
                base = (max(1, int(page)) - 1) * (self._page_size or len(items) or 0)
                item.seq_no = base + offset + 1
            else:
                item.seq_no = int(item.payload.pop("seq_no"))
        return self.require_items(items, page_url)

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------
    def parse_detail(self, item: ListItem) -> DetailResult:
        """解析详情页：正文 / 图片集 / 视频地址。"""
        soup = self.fetch_soup(item.url)
        content_selector = self.cfg("detail_content_selector", None)
        image_selector = self.cfg("detail_image_selector", None)
        video_selector = self.cfg("detail_video_selector", None)
        title_selector = self.cfg("detail_title_selector", None)

        title = item.title
        if title_selector:
            title = self.extract(soup, str(title_selector)) or title

        content = ""
        if content_selector:
            content = self.extract(soup, str(content_selector))

        images: list[str] = []
        if image_selector:
            images = [self.absolute(src, item.url) for src in self.extract_all(soup, str(image_selector))]

        video_url: str | None = None
        if video_selector:
            video_url = self.absolute(self.extract(soup, str(video_selector)), item.url) or None
        if not video_url and item.url.lower().split("?")[0].endswith(".m3u8"):
            video_url = item.url

        detail_type = str(getattr(self.ds, "type", ""))
        if detail_type == "text" and not content and not content_selector:
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                "未配置 detail_content_selector，无法解析正文",
                retryable=False,
            )
        if detail_type == "image" and not images and not image_selector:
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                "未配置 detail_image_selector，无法解析图片列表",
                retryable=False,
            )
        if detail_type == "video" and not video_url:
            raise BizError(
                ErrCode.M3U8_PARSE,
                "未在详情页解析到 m3u8 地址",
                retryable=False,
                detail=f"url={item.url}",
            )
        return DetailResult(title=title, content=content, images=images, video_url=video_url)

    # ------------------------------------------------------------------
    # 总页数
    # ------------------------------------------------------------------
    def parse_pages(self, url: str) -> int | None:
        """解析总页数：``total_pages`` 固定值 → 选择器文本 → 正则 → None。"""
        fixed = self.cfg("total_pages", None)
        if fixed is not None:
            try:
                return max(0, int(fixed))
            except (TypeError, ValueError):
                return None
        selector = self.cfg("total_pages_selector", None)
        if not selector:
            return None
        try:
            soup = self.fetch_soup(self.build_url(url, 1))
            raw = self.extract(soup, str(selector))
        except BizError:
            return None
        if not raw:
            return None
        pattern = str(self.cfg("total_pages_regex", r"(\d+)"))
        match = re.search(pattern, raw)
        if not match:
            return None
        try:
            return max(0, int(match.group(1)))
        except (IndexError, ValueError):
            return None
