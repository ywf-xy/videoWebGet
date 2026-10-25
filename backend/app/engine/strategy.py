"""三种获取策略计算（PRD 第 7 章全部边界）+ 游标推进。

纯计算层：只依赖 parser 接口与已算好的历史指纹集合，**不访问数据库**，
便于用假 parser 单测（T08 验收点④）。

边界覆盖清单（PRD 7.2）：
- S1 首次游标=0 / n>总数 → success_with_warning / 列表空 → 0 任务 / 自动翻页补足
- S2 起始页越界 → failed(3008) / 页数越界 → 截断+WARN / 中间页空 → 停止 / 页失败 → skipped 继续
- S3 缺日期 → 保留+WARN / 指纹命中 → skipped / 跨度>365 → 拦截
- 任意策略去重后 0 条 → success + 「没有需要采集的新内容」
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.common.errors import BizError, ErrCode
from app.common.fingerprint import item_fingerprint
from app.common.logger import get_logger
from app.common.timeutil import parse_date
from app.config import DEFAULTS, E
from app.parsers.base import ListItem

logger = get_logger(__name__)

#: 日志回调签名 (level, message)
LogFn = Callable[[str, str], None]


class ParserLike(Protocol):
    """策略层需要的解析器最小接口。"""

    def parse_list(self, url: str, page: int = 1) -> list[ListItem]: ...

    def parse_pages(self, url: str) -> int | None: ...


@dataclass
class StrategyResult:
    """阶段一结果。"""

    items: list[ListItem] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    cursor_after: dict[str, Any] = field(default_factory=dict)
    status: str = E.BATCH_SUCCESS
    error: BizError | None = None
    empty: bool = False
    parsed_pages: int = 0

    @property
    def ok(self) -> bool:
        """阶段一是否成功（未抛错即成功，即使 0 条）。"""
        return self.error is None


def _noop_log(_level: str, _message: str) -> None:
    """默认空日志回调。"""


class StrategyResolver:
    """按策略从列表页解析出待建任务的条目集合。"""

    def __init__(
        self,
        ds: Any,
        parser: ParserLike,
        known_fingerprints: set[str] | None = None,
        log: LogFn | None = None,
    ) -> None:
        self.ds = ds
        self.parser = parser
        self.known: set[str] = set(known_fingerprints or ())
        self.max_pages: int = int(DEFAULTS["strategy.max_pages"])
        self._log: LogFn = log or _noop_log
        self.base: str = str(
            getattr(ds, "current_url", None) or getattr(ds, "homepage_url", "") or ""
        )
        self.cursor: dict[str, Any] = {
            "last_item_no": int(getattr(ds, "cursor_last_item_no", 0) or 0),
            "last_page": int(getattr(ds, "cursor_last_page", 0) or 0),
            "last_success_date": getattr(ds, "cursor_last_success_date", None),
        }

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def resolve(self, strategy: str, params: dict[str, Any] | None = None) -> StrategyResult:
        """按策略解析；捕获 BizError 并转换为 ``status=failed`` 的结果。

        阶段一失败时游标保持 ``cursor_before``（不推进）。
        """
        payload = dict(params or {})
        result = StrategyResult(cursor_after=dict(self.cursor))
        try:
            if strategy == E.STRATEGY_COUNT:
                self._by_count(result, payload)
            elif strategy == E.STRATEGY_PAGE:
                self._by_page(result, payload)
            elif strategy == E.STRATEGY_DATE:
                self._by_date(result, payload)
            else:
                raise BizError(ErrCode.PARAM_INVALID, f"未知策略：{strategy}")
        except BizError as exc:
            result.status = E.BATCH_FAILED
            result.error = exc
            result.items = []
            result.cursor_after = dict(self.cursor)  # 失败不推进游标
            self._log(E.LOG_ERROR, f"阶段一失败：{exc.message}")
            logger.warning("策略 %s 阶段一失败：%s", strategy, exc)
        return result

    # ------------------------------------------------------------------
    # S1 按条数
    # ------------------------------------------------------------------
    def _by_count(self, result: StrategyResult, params: dict[str, Any]) -> None:
        """从游标之后取 n 条，不足时自动翻页补足。"""
        try:
            n = int(params.get("n"))
        except (TypeError, ValueError) as exc:
            raise BizError(ErrCode.PARAM_INVALID, "条数 n 必须为整数") from exc
        if not 1 <= n <= int(DEFAULTS["strategy.n_max"]):
            raise BizError(
                ErrCode.PARAM_INVALID, f"条数需在 1-{DEFAULTS['strategy.n_max']} 之间"
            )

        last_item_no = int(self.cursor.get("last_item_no") or 0)
        collected: list[ListItem] = []
        page = 1
        last_parsed_page = 0

        while len(collected) < n and page <= self.max_pages:
            try:
                batch = self.parser.parse_list(self.base, page)
            except BizError as exc:
                if page == 1:
                    raise  # 首页失败 → 阶段一失败
                result.warnings.append(f"第{page}页请求失败（{exc.code}），已停止翻页")
                self._log(E.LOG_WARN, f"第{page}页请求失败：{exc.message}")
                break
            if not batch:
                if page == 1:
                    result.warnings.append("列表解析结果为空，请检查解析脚本或网址")
                break
            for item in batch:
                if int(item.seq_no) > last_item_no:  # 首次游标=0 → 全部通过
                    collected.append(item)
                if len(collected) >= n:
                    break
            last_parsed_page = page
            self._log(E.LOG_INFO, f"已翻至第 {page} 页，累计命中 {len(collected)} 条")
            page += 1

        result.parsed_pages = last_parsed_page
        candidates = len(collected)
        items = self._dedup(collected, limit=n)
        result.items = items
        result.skipped += max(0, candidates - len(items))
        if candidates > len(items):
            self._log(E.LOG_INFO, f"去重跳过 {candidates - len(items)} 条")

        if not items:
            # 边界：无新内容 → success + 0 任务（S1 仅推进 last_page）
            result.status = E.BATCH_SUCCESS
            result.empty = True
            if not result.warnings:
                result.warnings.append("没有需要采集的新内容")
            result.cursor_after = {
                "last_item_no": last_item_no,
                "last_page": last_parsed_page,
                "last_success_date": self.cursor.get("last_success_date"),
            }
            return

        if len(items) < n:
            result.status = E.BATCH_SUCCESS_WITH_WARNING
            result.warnings.append(
                f"请求 {n} 条，实际获取 {len(items)} 条（已到列表末尾）"
            )
        else:
            result.status = E.BATCH_SUCCESS

        max_seq = max(int(item.seq_no) for item in items)
        result.cursor_after = {
            "last_item_no": max(max_seq, last_item_no),
            "last_page": max(last_parsed_page, int(self.cursor.get("last_page") or 0)),
            "last_success_date": self.cursor.get("last_success_date"),
        }

    # ------------------------------------------------------------------
    # S2 按分页
    # ------------------------------------------------------------------
    def _by_page(self, result: StrategyResult, params: dict[str, Any]) -> None:
        """从 start 页起连续取 pages 页，越界截断、空页提前结束。"""
        try:
            start = int(params.get("start"))
            pages = int(params.get("pages"))
        except (TypeError, ValueError) as exc:
            raise BizError(ErrCode.PARAM_INVALID, "起始页与页数必须为整数") from exc
        if start < 1:
            raise BizError(ErrCode.PARAM_INVALID, "起始页需 ≥ 1")
        if not 1 <= pages <= int(DEFAULTS["strategy.pages_max"]):
            raise BizError(
                ErrCode.PARAM_INVALID, f"页数需在 1-{DEFAULTS['strategy.pages_max']} 之间"
            )

        total = self.parser.parse_pages(self.base)
        if total is not None and start > total:
            raise BizError(
                ErrCode.PAGE_OUT_OF_RANGE,
                f"起始页 {start} 超出总页数 {total}，请调整",
                detail=f"start={start}, total={total}",
            )
        requested_end = start + pages - 1
        end = requested_end if total is None else min(requested_end, total)

        collected: list[ListItem] = []
        last_ok_page = start - 1
        for page in range(start, end + 1):
            try:
                batch = self.parser.parse_list(self.base, page)
            except BizError as exc:
                result.warnings.append(f"第{page}页请求失败（{exc.code}），已跳过")
                result.skipped += 1
                self._log(E.LOG_ERROR, f"page={page} {exc.code}｜{exc.message}")
                continue
            if not batch:
                result.warnings.append(f"第{page}页无数据，采集提前结束")
                self._log(E.LOG_WARN, f"第{page}页无数据，采集提前结束")
                break
            collected.extend(batch)
            last_ok_page = page
            self._log(E.LOG_INFO, f"第 {page} 页解析到 {len(batch)} 条")

        result.parsed_pages = max(0, last_ok_page - start + 1)
        candidates = len(collected)
        result.items = self._dedup(collected)
        result.skipped += max(0, candidates - len(result.items))

        if total is not None and end < requested_end:
            result.status = E.BATCH_SUCCESS_WITH_WARNING
            result.warnings.append(
                f"请求 {pages} 页，实际获取 {end - start + 1} 页（已到最后一页）"
            )
        elif result.skipped > 0:
            result.status = E.BATCH_SUCCESS_WITH_WARNING
        else:
            result.status = E.BATCH_SUCCESS

        if not result.items:
            result.empty = True
            if not result.warnings:
                result.warnings.append("没有需要采集的新内容")

        result.cursor_after = {
            "last_item_no": int(self.cursor.get("last_item_no") or 0),
            "last_page": max(last_ok_page, 0),
            "last_success_date": self.cursor.get("last_success_date"),
        }

    # ------------------------------------------------------------------
    # S3 按日期
    # ------------------------------------------------------------------
    def _by_date(self, result: StrategyResult, params: dict[str, Any]) -> None:
        """取日期区间内条目，并按历史成功指纹去重。"""
        date_from = parse_date(str(params.get("from") or params.get("date_from") or ""))
        date_to = parse_date(str(params.get("to") or params.get("date_to") or ""))
        if date_from is None or date_to is None:
            raise BizError(ErrCode.PARAM_INVALID, "开始日期与结束日期必须为 yyyy-MM-dd 格式")
        if date_to < date_from:
            raise BizError(ErrCode.PARAM_INVALID, "结束日期不能早于开始日期")
        if (date_to - date_from).days > int(DEFAULTS["strategy.date_span_days"]):
            raise BizError(ErrCode.PARAM_INVALID, "日期跨度不能超过 365 天")

        lower = date_from.strftime("%Y-%m-%d")
        upper = date_to.strftime("%Y-%m-%d")

        all_items: list[ListItem] = []
        page = 1
        while page <= self.max_pages:
            try:
                batch = self.parser.parse_list(self.base, page)
            except BizError as exc:
                if page == 1:
                    raise
                result.warnings.append(f"第{page}页请求失败（{exc.code}），已停止翻页")
                self._log(E.LOG_WARN, f"第{page}页请求失败：{exc.message}")
                break
            if not batch:
                break
            all_items.extend(batch)
            result.parsed_pages = page
            self._log(E.LOG_INFO, f"第 {page} 页解析到 {len(batch)} 条")
            page += 1

        candidates: list[ListItem] = []
        for item in all_items:
            if item.date is None:
                # 边界：缺日期 → 不参与过滤，保留并 WARN
                result.warnings.append(f"条目「{item.title}」缺少日期字段，已按保留处理")
                self._log(E.LOG_WARN, f"条目「{item.title}」缺少日期字段，已按保留处理")
                candidates.append(item)
            elif lower <= item.date <= upper:
                candidates.append(item)

        fresh: list[ListItem] = []
        seen: set[str] = set()
        for item in candidates:
            fingerprint = item_fingerprint(item.url, item.title)
            if fingerprint in self.known:
                result.skipped += 1
                continue
            if fingerprint in seen:
                result.skipped += 1
                continue
            seen.add(fingerprint)
            fresh.append(item)

        result.items = fresh
        if result.skipped:
            result.status = E.BATCH_SUCCESS_WITH_WARNING
            self._log(E.LOG_INFO, f"跳过 {result.skipped} 条（已采集过）")
        if not fresh:
            result.empty = True
            if not result.warnings:
                result.warnings.append("没有需要采集的新内容")

        success_dates = [item.date for item in fresh if item.date]
        max_date = max(success_dates) if success_dates else self.cursor.get("last_success_date")
        result.cursor_after = {
            "last_item_no": int(self.cursor.get("last_item_no") or 0),
            "last_page": max(int(self.cursor.get("last_page") or 0), result.parsed_pages),
            "last_success_date": max_date,
        }

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _dedup(items: Sequence[ListItem], limit: int | None = None) -> list[ListItem]:
        """按条目指纹去重并保持原始顺序。"""
        seen: set[str] = set()
        result: list[ListItem] = []
        for item in items:
            fingerprint = item_fingerprint(item.url, item.title)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            result.append(item)
            if limit is not None and len(result) >= limit:
                break
        return result


__all__ = ["ParserLike", "StrategyResolver", "StrategyResult"]
