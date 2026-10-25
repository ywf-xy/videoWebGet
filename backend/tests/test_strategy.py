"""三种获取策略 × PRD 7.2 边界情况逐条断言（纯计算层，无 DB / 无网络）。"""

from __future__ import annotations

from typing import Any

import pytest

from app.common.errors import BizError, ErrCode
from app.common.fingerprint import item_fingerprint
from app.config import E
from app.engine.strategy import StrategyResolver
from app.parsers.base import ListItem


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------
class FakeDS:
    """StrategyResolver 需要的数据源最小替身。"""

    def __init__(
        self,
        *,
        name: str = "假数据源",
        category: str | None = "测试",
        is_novel: bool = False,
        homepage_url: str = "http://fake.test/list",
        current_url: str | None = None,
        cursor_last_item_no: int = 0,
        cursor_last_page: int = 0,
        cursor_last_success_date: str | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.is_novel = is_novel
        self.homepage_url = homepage_url
        self.current_url = current_url
        self.cursor_last_item_no = cursor_last_item_no
        self.cursor_last_page = cursor_last_page
        self.cursor_last_success_date = cursor_last_success_date


class FakeParser:
    """按页码返回固定条目的假解析器（可注入页级失败 / 总页数）。"""

    def __init__(
        self,
        pages: dict[int, list[ListItem]],
        *,
        total_pages: int | None = None,
        fail_pages: dict[int, int] | None = None,
    ) -> None:
        self.pages = pages
        self.total_pages = total_pages
        self.fail_pages = dict(fail_pages or {})
        self.calls: list[int] = []

    def parse_list(self, url: str, page: int = 1) -> list[ListItem]:
        self.calls.append(int(page))
        if int(page) in self.fail_pages:
            raise BizError(self.fail_pages[int(page)], f"第 {page} 页请求失败")
        return list(self.pages.get(int(page), []))

    def parse_pages(self, url: str) -> int | None:
        return self.total_pages


def mk_item(seq: int, date: str | None = None, title: str | None = None) -> ListItem:
    """构造一个列表条目。"""
    return ListItem(
        title=title or f"条目{seq}",
        url=f"http://fake.test/detail/{seq}",
        seq_no=int(seq),
        date=date,
    )


def mk_pages(count: int, per_page: int = 2, *, date: str | None = None) -> dict[int, list[ListItem]]:
    """构造 ``count`` 条条目、每页 ``per_page`` 条的页字典。"""
    pages: dict[int, list[ListItem]] = {}
    for index in range(count):
        page = index // per_page + 1
        pages.setdefault(page, []).append(mk_item(index + 1, date=date))
    return pages


def resolve(
    parser: FakeParser, strategy: str, params: dict[str, Any], ds: FakeDS | None = None, **kwargs: Any
):
    """执行策略解析。"""
    resolver = StrategyResolver(ds or FakeDS(), parser, **kwargs)
    return resolver.resolve(strategy, params)


# ---------------------------------------------------------------------------
# S1 按指定条数
# ---------------------------------------------------------------------------
class TestStrategyCount:
    """S1 边界：首次游标 / n 超总数 / 列表空 / 自动翻页 / 游标推进。"""

    def test_first_run_without_cursor_starts_from_first_item(self) -> None:
        """首次爬取：无历史游标视为 0，从第 1 条开始取 n 条。"""
        parser = FakeParser({1: [mk_item(1), mk_item(2), mk_item(3)]})
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 2}, ds=FakeDS(cursor_last_item_no=0))
        assert [item.seq_no for item in result.items] == [1, 2]
        assert result.status == E.BATCH_SUCCESS
        assert result.empty is False
        assert result.cursor_after["last_item_no"] == 2

    def test_cursor_filters_out_historical_items(self) -> None:
        """游标之后取：``seq_no <= cursor`` 的条目被过滤。"""
        parser = FakeParser({1: [mk_item(1), mk_item(2)], 2: [mk_item(3), mk_item(4)]})
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 1}, ds=FakeDS(cursor_last_item_no=2))
        assert [item.seq_no for item in result.items] == [3]
        assert result.cursor_after["last_item_no"] == 3

    def test_n_greater_than_total_yields_success_with_warning(self) -> None:
        """n 超过剩余总数：取到末尾为止，批次 success_with_warning。"""
        parser = FakeParser(mk_pages(5))
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 10})
        assert len(result.items) == 5
        assert result.status == E.BATCH_SUCCESS_WITH_WARNING
        assert any("实际获取 5 条" in text for text in result.warnings)

    def test_empty_list_yields_zero_tasks_and_success(self) -> None:
        """S1 列表为空：0 任务、批次 success。"""
        result = resolve(FakeParser({1: []}), E.STRATEGY_COUNT, {"n": 3})
        assert result.items == []
        assert result.status == E.BATCH_SUCCESS
        assert result.empty is True
        assert any("列表解析结果为空" in text for text in result.warnings)

    def test_auto_turn_page_to_fill_n(self) -> None:
        """游标之后不足 n 条：自动翻页补足。"""
        parser = FakeParser({1: [mk_item(1), mk_item(2)], 2: [mk_item(3), mk_item(4)]})
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 2}, ds=FakeDS(cursor_last_item_no=2))
        assert [item.seq_no for item in result.items] == [3, 4]
        assert parser.calls == [1, 2]
        assert result.parsed_pages == 2

    def test_stops_turning_when_reaching_list_end(self) -> None:
        """列表到底即停止翻页（不无限翻页）。"""
        parser = FakeParser({1: [mk_item(1)]})
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 5})
        assert len(result.items) == 1
        assert parser.calls == [1, 2], "空页后应再请求一次即停止（首次空页判定）"

    def test_first_page_failure_fails_phase_and_keeps_cursor(self) -> None:
        """阶段一首页失败：状态 failed，不推进游标（PRD 7.4）。"""
        parser = FakeParser({1: [mk_item(1)]}, fail_pages={1: int(ErrCode.HTTP_ERROR)})
        ds = FakeDS(cursor_last_item_no=7, cursor_last_page=3)
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 2}, ds=ds)
        assert result.status == E.BATCH_FAILED
        assert result.error is not None and result.error.code == int(ErrCode.HTTP_ERROR)
        assert result.items == []
        assert result.cursor_after["last_item_no"] == 7, "阶段一失败不得推进游标"
        assert result.cursor_after["last_page"] == 3

    def test_later_page_failure_keeps_parsed_items(self) -> None:
        """非首页失败：保留已解析条目并记 WARN（不整体失败）。"""
        parser = FakeParser(
            {1: [mk_item(1), mk_item(2)]}, fail_pages={2: int(ErrCode.HTTP_ERROR)}
        )
        result = resolve(parser, E.STRATEGY_COUNT, {"n": 5})
        assert len(result.items) == 2
        assert result.ok is True
        assert any("第2页请求失败" in text for text in result.warnings)

    def test_duplicate_items_are_deduped_and_counted_as_skipped(self) -> None:
        """同页重复条目按指纹去重，计入 skipped。"""
        duplicated = [mk_item(1), mk_item(1)]
        result = resolve(FakeParser({1: duplicated}), E.STRATEGY_COUNT, {"n": 5})
        assert len(result.items) == 1
        assert result.skipped == 1

    def test_dedup_to_zero_yields_success_and_zero_tasks(self) -> None:
        """任意策略去重后 0 条：success + 0 任务 + 「没有需要采集的新内容」。"""
        result = resolve(FakeParser({1: []}), E.STRATEGY_COUNT, {"n": 3})
        assert result.items == []
        assert result.status == E.BATCH_SUCCESS
        assert result.skipped == 0

    @pytest.mark.parametrize("bad_n", [0, -1, 10000, "abc", None])
    def test_invalid_n_rejected_with_1001(self, bad_n: object) -> None:
        """n 非法（越界/非整数）→ 1001 PARAM_INVALID。"""
        params: dict[str, Any] = {} if bad_n is None else {"n": bad_n}
        result = resolve(FakeParser({1: [mk_item(1)]}), E.STRATEGY_COUNT, params)
        assert result.status == E.BATCH_FAILED
        assert result.error is not None
        assert result.error.code == int(ErrCode.PARAM_INVALID)


# ---------------------------------------------------------------------------
# S2 按分页
# ---------------------------------------------------------------------------
class TestStrategyPage:
    """S2 边界：起始页越界 / 页数截断 / 中间页空 / 页请求失败 / 总页数未知。"""

    def test_start_page_beyond_total_raises_page_out_of_range(self) -> None:
        """起始页大于总页数：failed(3008)，游标不推进。"""
        parser = FakeParser({1: [mk_item(1)]}, total_pages=3)
        ds = FakeDS(cursor_last_page=2)
        result = resolve(parser, E.STRATEGY_PAGE, {"start": 5, "pages": 2}, ds=ds)
        assert result.status == E.BATCH_FAILED
        assert result.error is not None
        assert result.error.code == int(ErrCode.PAGE_OUT_OF_RANGE) == 3008
        assert result.items == []
        assert result.cursor_after["last_page"] == 2

    def test_pages_truncated_to_last_page_with_warning(self) -> None:
        """页数越界：截断到最后一页 + success_with_warning。"""
        parser = FakeParser(
            {1: [mk_item(1), mk_item(2)], 2: [mk_item(3), mk_item(4)], 3: [mk_item(5)]},
            total_pages=3,
        )
        result = resolve(parser, E.STRATEGY_PAGE, {"start": 2, "pages": 5})
        assert [item.seq_no for item in result.items] == [3, 4, 5]
        assert result.status == E.BATCH_SUCCESS_WITH_WARNING
        assert any("已到最后一页" in text for text in result.warnings)
        assert result.cursor_after["last_page"] == 3

    def test_empty_middle_page_stops_immediately(self) -> None:
        """中间某页为空：视为列表结束，已解析条目照常返回。"""
        parser = FakeParser(
            {1: [mk_item(1), mk_item(2)], 2: [], 3: [mk_item(9)]}, total_pages=3
        )
        result = resolve(parser, E.STRATEGY_PAGE, {"start": 1, "pages": 3})
        assert [item.seq_no for item in result.items] == [1, 2]
        assert any("第2页无数据" in text for text in result.warnings)
        assert 3 not in parser.calls, "空页后不得继续翻页"

    def test_page_request_failure_is_skipped_and_continues(self) -> None:
        """某页请求失败：该页 skipped，继续后续页，批次 success_with_warning。"""
        parser = FakeParser(
            {1: [mk_item(1)], 2: [mk_item(2)], 3: [mk_item(3)]},
            total_pages=3,
            fail_pages={2: int(ErrCode.HTTP_ERROR)},
        )
        result = resolve(parser, E.STRATEGY_PAGE, {"start": 1, "pages": 3})
        assert [item.seq_no for item in result.items] == [1, 3]
        assert result.skipped == 1
        assert result.status == E.BATCH_SUCCESS_WITH_WARNING
        assert any("第2页请求失败" in text for text in result.warnings)

    def test_unknown_total_pages_uses_requested_range(self) -> None:
        """总页数未知（解析不出）：按请求范围取页。"""
        parser = FakeParser({1: [mk_item(1)], 2: [mk_item(2)]}, total_pages=None)
        result = resolve(parser, E.STRATEGY_PAGE, {"start": 1, "pages": 2})
        assert [item.seq_no for item in result.items] == [1, 2]
        assert result.status == E.BATCH_SUCCESS
        assert result.cursor_after["last_page"] == 2

    @pytest.mark.parametrize(
        "params",
        [
            {"start": 0, "pages": 1},
            {"start": 1, "pages": 0},
            {"start": 1, "pages": 501},
            {"pages": 1},
        ],
    )
    def test_invalid_page_params_rejected(self, params: dict[str, Any]) -> None:
        """分页参数越界 → 1001。"""
        result = resolve(FakeParser({1: [mk_item(1)]}, total_pages=5), E.STRATEGY_PAGE, params)
        assert result.status == E.BATCH_FAILED
        assert result.error is not None
        assert result.error.code == int(ErrCode.PARAM_INVALID)


# ---------------------------------------------------------------------------
# S3 按日期
# ---------------------------------------------------------------------------
class TestStrategyDate:
    """S3 边界：区间过滤 / 缺日期 / 指纹去重 / 跨度上限。"""

    def _dated_pages(self) -> dict[int, list[ListItem]]:
        return {
            1: [mk_item(1, date="2026-10-01"), mk_item(2, date="2026-10-02")],
            2: [mk_item(3, date="2026-10-03"), mk_item(4, date="2026-10-05")],
        }

    def test_filters_items_by_date_range(self) -> None:
        """仅保留区间内条目（闭区间）。"""
        result = resolve(
            FakeParser(self._dated_pages()),
            E.STRATEGY_DATE,
            {"from": "2026-10-02", "to": "2026-10-03"},
        )
        assert [item.seq_no for item in result.items] == [2, 3]
        assert result.skipped == 0
        assert result.status == E.BATCH_SUCCESS

    def test_item_without_date_is_kept_with_warning(self) -> None:
        """区间内条目无日期字段：不参与过滤，默认保留并记 WARN。"""
        pages = {1: [mk_item(1, date=None), mk_item(2, date="2026-10-02")]}
        result = resolve(
            FakeParser(pages), E.STRATEGY_DATE, {"from": "2026-10-01", "to": "2026-10-31"}
        )
        assert [item.seq_no for item in result.items] == [1, 2]
        assert any("缺少日期字段" in text for text in result.warnings)

    def test_known_fingerprint_is_skipped(self) -> None:
        """条目日期命中历史成功指纹：跳过、不建任务、计数 skipped。"""
        pages = {1: [mk_item(1, date="2026-10-02"), mk_item(2, date="2026-10-03")]}
        known = {item_fingerprint("http://fake.test/detail/1", "条目1")}
        result = resolve(
            FakeParser(pages),
            E.STRATEGY_DATE,
            {"from": "2026-10-01", "to": "2026-10-31"},
            known_fingerprints=known,
        )
        assert [item.seq_no for item in result.items] == [2]
        assert result.skipped == 1
        assert result.status == E.BATCH_SUCCESS_WITH_WARNING

    def test_all_candidates_deduped_yields_empty_success(self) -> None:
        """全部命中历史指纹：0 任务 + success + skipped 计数。"""
        pages = {1: [mk_item(1, date="2026-10-02")]}
        known = {item_fingerprint("http://fake.test/detail/1", "条目1")}
        result = resolve(
            FakeParser(pages),
            E.STRATEGY_DATE,
            {"from": "2026-10-01", "to": "2026-10-31"},
            known_fingerprints=known,
        )
        assert result.items == []
        assert result.skipped == 1
        assert result.empty is True

    def test_duplicate_candidates_counted_as_skipped(self) -> None:
        """同批次内重复条目：保留一条，其余计入 skipped。"""
        pages = {
            1: [mk_item(1, date="2026-10-02")],
            2: [mk_item(1, date="2026-10-02")],
        }
        result = resolve(
            FakeParser(pages), E.STRATEGY_DATE, {"from": "2026-10-01", "to": "2026-10-31"}
        )
        assert len(result.items) == 1
        assert result.skipped == 1

    def test_span_over_365_days_rejected(self) -> None:
        """区间跨度超 365 天：1001（表单层已拦，服务端二次校验）。"""
        result = resolve(
            FakeParser({1: []}),
            E.STRATEGY_DATE,
            {"from": "2026-01-01", "to": "2027-06-01"},
        )
        assert result.status == E.BATCH_FAILED
        assert result.error is not None
        assert result.error.code == int(ErrCode.PARAM_INVALID)
        assert "365" in result.error.message

    @pytest.mark.parametrize(
        "params",
        [
            {"from": "2026-13-01", "to": "2026-10-01"},
            {"from": "2026-10-05", "to": "2026-10-01"},
            {"to": "2026-10-01"},
        ],
    )
    def test_invalid_date_params_rejected(self, params: dict[str, Any]) -> None:
        """日期格式非法 / 结束早于开始 / 缺字段 → 1001。"""
        result = resolve(FakeParser({1: []}), E.STRATEGY_DATE, params)
        assert result.status == E.BATCH_FAILED
        assert result.error is not None
        assert result.error.code == int(ErrCode.PARAM_INVALID)

    def test_cursor_records_max_success_date(self) -> None:
        """游标取成功项中的最大日期（不取 to，避免未完成条目被永久跳过）。"""
        result = resolve(
            FakeParser(self._dated_pages()),
            E.STRATEGY_DATE,
            {"from": "2026-10-01", "to": "2026-10-31"},
        )
        assert result.cursor_after["last_success_date"] == "2026-10-05"


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------
def test_unknown_strategy_rejected() -> None:
    """未知策略名 → 1001。"""
    result = resolve(FakeParser({1: []}), "unknown", {})
    assert result.status == E.BATCH_FAILED
    assert result.error is not None
    assert result.error.code == int(ErrCode.PARAM_INVALID)


def test_cursor_before_is_echoed_when_nothing_new() -> None:
    """无新内容时游标保持原值（S1）。"""
    ds = FakeDS(cursor_last_item_no=9, cursor_last_page=4, cursor_last_success_date="2026-10-01")
    result = resolve(FakeParser({1: [mk_item(1), mk_item(2)]}), E.STRATEGY_COUNT, {"n": 2}, ds=ds)
    assert result.items == []
    assert result.cursor_after["last_item_no"] == 9
    assert result.cursor_after["last_success_date"] == "2026-10-01"
