"""图集解析器：列表结构同 HTML 列表，详情解析出图片地址数组（保持原始顺序）。"""

from __future__ import annotations

from typing import Any, Final

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.parsers.base import DetailResult, ListItem
from app.parsers.html_list_parser import HtmlListParser

logger = get_logger(__name__)

#: 默认图片选择器
DEFAULT_IMAGE_SELECTOR: Final[str] = "img@src"


class ImageSetParser(HtmlListParser):
    """图片集解析器（一个图集 = 一个任务）。"""

    name = "image_set"

    def __init__(self, ds: Any, http: Any = None) -> None:
        super().__init__(ds, http)

    def parse_detail(self, item: ListItem) -> DetailResult:
        """解析图集详情，返回按列表顺序排列的图片绝对地址。"""
        soup = self.fetch_soup(item.url)
        selector = self.cfg("detail_image_selector", DEFAULT_IMAGE_SELECTOR)
        title_selector = self.cfg("detail_title_selector", None)

        title = item.title
        if title_selector:
            title = self.extract(soup, str(title_selector)) or title

        images: list[str] = []
        seen: set[str] = set()
        for source in self.extract_all(soup, str(selector)):
            absolute = self.absolute(source, item.url)
            if not absolute or absolute in seen:
                continue
            seen.add(absolute)
            images.append(absolute)

        if not images:
            raise BizError(
                ErrCode.SCRIPT_ERROR,
                f"图集未解析到任何图片：{item.title}",
                retryable=False,
                detail=f"selector={selector}",
            )
        return DetailResult(title=title, images=images)
