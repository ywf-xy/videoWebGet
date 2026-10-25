"""解析器基类与公共数据结构。

``ListItem`` 字段固定：``title / url / seq_no / date / payload``（T05 验收点①）。
内置解析器仅凭 ``data_source.config_json`` 的 CSS 选择器即可工作。

选择器语法：``css[@attr]``，``attr=text`` 取文本，``attr=html`` 取内部 HTML，
其余按属性名取值（如 ``a@href``、``img@src``、``time@datetime``）。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.downloader.http_client import HttpClient

logger = get_logger(__name__)

#: 日期归一化正则（支持 2026-10-25 / 2026/10/25 / 2026年10月25日）
_DATE_RE: Final[re.Pattern[str]] = re.compile(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")


class SourceLike(Protocol):
    """解析器需要的数据源最小接口。"""

    name: str
    type: str
    category: str | None
    homepage_url: str
    current_url: str | None
    script: str | None
    script_entry: str
    config_json: dict[str, Any]
    is_novel: int | bool


@dataclass
class ListItem:
    """列表条目（阶段一产物，也是建任务的输入）。"""

    title: str
    url: str
    seq_no: int = 0
    date: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """序列化为 crawl_task.payload。"""
        data = dict(self.payload or {})
        data.setdefault("seq_no", self.seq_no)
        if self.date:
            data.setdefault("date", self.date)
        return data


@dataclass
class DetailResult:
    """详情解析结果。"""

    title: str = ""
    content: str = ""
    images: list[str] = field(default_factory=list)
    video_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def normalize_date(text: str | None) -> str | None:
    """把各种日期写法归一化为 ``yyyy-MM-dd``，失败返回 None。"""
    if not text:
        return None
    match = _DATE_RE.search(str(text))
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def split_selector(expression: str | None) -> tuple[str, str]:
    """拆分 ``css@attr`` 选择器，返回 (css, attr)。attr 缺省为 ``text``。"""
    text = str(expression or "").strip()
    if not text:
        return "", "text"
    if "@" not in text:
        return text, "text"
    css, _, attr = text.rpartition("@")
    return css.strip(), (attr.strip() or "text").lower()


class BaseParser(ABC):
    """解析器抽象基类。"""

    name: str = "base"

    def __init__(self, ds: SourceLike, http: HttpClient | None = None) -> None:
        self.ds = ds
        self.http: HttpClient = http or HttpClient()
        self.config: dict[str, Any] = dict(getattr(ds, "config_json", None) or {})

    # ------------------------------------------------------------------
    # 配置读取
    # ------------------------------------------------------------------
    def cfg(self, key: str, default: Any = None) -> Any:
        """读取 config_json 中的配置项。"""
        value = self.config.get(key, default)
        return default if value in (None, "") else value

    def base_url(self) -> str:
        """当前生效地址（current_url 优先）。"""
        return str(getattr(self.ds, "current_url", None) or getattr(self.ds, "homepage_url", ""))

    def build_url(self, url: str, page: int) -> str:
        """按 ``list_url`` 模板或 ``page_param`` 生成翻页地址。"""
        template = str(self.cfg("list_url", "") or url)
        page = max(1, int(page))
        if "{page}" in template:
            return template.replace("{page}", str(page))
        if page <= 1:
            return template
        param = str(self.cfg("page_param", "page") or "page")
        parts = urlsplit(template)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query[param] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    # ------------------------------------------------------------------
    # HTML 工具
    # ------------------------------------------------------------------
    def fetch_soup(self, url: str) -> BeautifulSoup:
        """抓取并解析 HTML（lxml 优先，缺失时回退 html.parser）。"""
        html = self.http.get_text(url)
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:  # noqa: BLE001 - lxml 缺失或解析异常时回退
            return BeautifulSoup(html, "html.parser")

    @staticmethod
    def node_text(node: Any) -> str:
        """节点文本（合并空白）。"""
        if node is None:
            return ""
        return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()

    def extract(self, node: Any, expression: str | None) -> str:
        """按 ``css@attr`` 从节点内提取单个值。"""
        css, attr = split_selector(expression)
        if not css:
            return ""
        found = node.select_one(css) if hasattr(node, "select_one") else None
        return self._value_of(found, attr)

    def extract_all(self, node: Any, expression: str | None) -> list[str]:
        """按 ``css@attr`` 提取全部匹配值。"""
        css, attr = split_selector(expression)
        if not css:
            return []
        nodes = node.select(css) if hasattr(node, "select") else []
        values = [self._value_of(item, attr) for item in nodes]
        return [value for value in values if value]

    def _value_of(self, node: Any, attr: str) -> str:
        """从节点取属性/文本。"""
        if node is None:
            return ""
        if attr in ("text", "string"):
            return self.node_text(node)
        if attr == "html":
            return str(node.decode_contents()) if hasattr(node, "decode_contents") else ""
        value = node.get(attr) if hasattr(node, "get") else None
        if isinstance(value, list):
            return " ".join(str(item) for item in value).strip()
        return str(value).strip() if value else ""

    def absolute(self, url: str, base: str | None = None) -> str:
        """相对地址转绝对地址。"""
        text = str(url or "").strip()
        if not text:
            return ""
        return urljoin(base or self.base_url(), text)

    # ------------------------------------------------------------------
    # 抽象接口
    # ------------------------------------------------------------------
    @abstractmethod
    def parse_list(self, url: str, page: int = 1) -> list[ListItem]:
        """解析一页列表。"""

    @abstractmethod
    def parse_detail(self, item: ListItem) -> DetailResult:
        """解析单条详情。"""

    def parse_pages(self, url: str) -> int | None:
        """解析总页数；无法解析时返回 None（S2 视作未知总页数）。"""
        fixed = self.cfg("total_pages", None)
        if fixed is not None:
            try:
                return max(0, int(fixed))
            except (TypeError, ValueError):
                return None
        return None

    # ------------------------------------------------------------------
    # 通用校验
    # ------------------------------------------------------------------
    @staticmethod
    def require_items(items: list[ListItem], url: str) -> list[ListItem]:
        """列表为空时仅记录日志（由策略层判定 success / 失败）。"""
        if not items:
            logger.warning("列表解析结果为空：%s", url)
        return items

    @staticmethod
    def detail_error(message: str, detail: str = "") -> BizError:
        """构造解析错误。"""
        return BizError(ErrCode.SCRIPT_ERROR, message, retryable=False, detail=detail)
