"""端到端链路：建数据源 → 建批次 → 终态 → 任务/产物落库 → 文件真实存在 → 游标推进。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import support
from app.common.timeutil import today_str
from app.config import E
from conftest import OUTPUT_ROOT


@pytest.fixture
def no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制下载器走「ffmpeg 缺失」路径（与机器是否安装 ffmpeg 无关）。"""
    from app.downloader import m3u8_downloader as downloader_module

    class _Missing:
        available = False
        version = None
        path = None

        def probe_duration(self, _path: Any) -> float:
            return 0.0

        def to_mp4(self, *_args: Any, **_kwargs: Any) -> str:
            raise AssertionError("ffmpeg 不可用时不应调用 to_mp4")

    monkeypatch.setattr(downloader_module, "get_ffmpeg", lambda: _Missing())


@pytest.fixture
def ffmpeg_precheck_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """让「创建视频批次」的前置 ffmpeg 校验通过（仅替换服务层探测）。"""
    from app.services import batch_service

    class _Available:
        available = True
        version = "test-stub"
        path = "test-stub"

    monkeypatch.setattr(batch_service, "get_ffmpeg", lambda: _Available())


# ---------------------------------------------------------------------------
# 文字链路（内置解析器）
# ---------------------------------------------------------------------------
class TestTextEndToEnd:
    """文字：两阶段执行、产物落盘、游标推进、首页数字联动、增量。"""

    def test_full_chain_writes_files_and_advances_cursor(
        self, client: TestClient, site: Any
    ) -> None:
        """完整链路：2 章 → 2 任务成功 → 2 个 txt 落盘（size>0）→ 游标推进。"""
        ds_id = support.create_source(client, site, name="某某小说网", is_novel=False)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        detail = support.wait_batch(client, batch_id)

        assert detail["status"] == E.BATCH_SUCCESS
        assert detail["phase"] == E.PHASE_DONE
        assert detail["total_tasks"] == 2
        assert detail["done_tasks"] == 2
        assert detail["failed_tasks"] == 0
        assert detail["progress"] == 100

        tasks = support.tasks_of(client, batch_id)
        assert [task["status"] for task in tasks] == [E.TASK_SUCCESS, E.TASK_SUCCESS]
        assert all(task["attempt_count"] == 1 for task in tasks)

        artifacts = support.artifacts_of(client, ds_id)
        assert len(artifacts) == 2
        for artifact in artifacts:
            path = Path(artifact["path"])
            assert path.exists(), f"产物文件不存在：{path}"
            assert path.stat().st_size > 0
            assert artifact["status"] == E.ARTIFACT_SUCCESS
            assert artifact["size"] > 0
            # 非小说模板：{root}/{数据源}/{分类}/{yyyy-MM-dd}/{标题}.txt
            expected_dir = OUTPUT_ROOT / "某某小说网" / "测试分类" / today_str()
            assert path.parent == expected_dir, f"落盘目录不符：{path.parent}"
            assert path.suffix == ".txt"

        source = support.source_detail(client, ds_id)
        assert source["cursor_last_item_no"] == 2, "全部成功后游标必须推进"
        assert source["total_items"] == 2
        assert source["last_success_at"] is not None

    def test_task_result_rows_persisted(self, client: TestClient, site: Any) -> None:
        """每条成功任务都有 task_result（P0-18②）。"""
        ds_id = support.create_source(client, site, name="结果表源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})
        support.wait_batch(client, batch_id)
        task = support.tasks_of(client, batch_id)[0]
        detail = support.unwrap(client.get(f"/api/tasks/{task['id']}"))
        assert detail["result"] is not None
        assert detail["result"]["artifact_type"] == E.ARTIFACT_TEXT
        assert detail["result"]["file_size"] > 0
        assert Path(detail["result"]["output_path"]).exists()

    def test_overview_numbers_follow_success_tasks(self, client: TestClient, site: Any) -> None:
        """首页 overview 的今日/本周/本月采集量与成功任务数一致。"""
        before = support.unwrap(client.get("/api/dashboard/overview"))
        ds_id = support.create_source(client, site, name="统计源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        support.wait_batch(client, batch_id)
        after = support.unwrap(client.get("/api/dashboard/overview"))

        assert after["today"] == before["today"] + 2
        assert after["week"] == before["week"] + 2
        assert after["month"] == before["month"] + 2
        assert after["health"]["total"] == before["health"]["total"] + 1

    def test_incremental_second_batch_only_new_items(
        self, client: TestClient, site: Any
    ) -> None:
        """增量：首次抓 4 条，站点新增 2 条后第二次只抓新增 2 条。"""
        ds_id = support.create_source(client, site, name="追更源")
        first = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 4})
        first_detail = support.wait_batch(client, first)
        assert first_detail["total_tasks"] == 4
        assert support.source_detail(client, ds_id)["cursor_last_item_no"] == 4

        site.chapters.extend(
            [
                {"id": 5, "title": "第005章 新增甲", "date": "2026-10-15"},
                {"id": 6, "title": "第006章 新增乙", "date": "2026-10-16"},
            ]
        )
        second = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        second_detail = support.wait_batch(client, second)
        assert second_detail["total_tasks"] == 2, "第二次只应抓到新增条目"

        titles = [task["title"] for task in support.tasks_of(client, second)]
        assert titles == ["第005章 新增甲", "第006章 新增乙"]
        assert support.source_detail(client, ds_id)["cursor_last_item_no"] == 6

    def test_n_greater_than_total_marks_warning(self, client: TestClient, site: Any) -> None:
        """n 超过总数：实际取到 3 条并标记 success_with_warning。"""
        site.chapters = site.chapters[:3]
        ds_id = support.create_source(client, site, name="少量源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 10})
        detail = support.wait_batch(client, batch_id)
        assert detail["total_tasks"] == 3
        assert detail["done_tasks"] == 3
        assert detail["status"] == E.BATCH_SUCCESS_WITH_WARNING
        assert any("实际获取 3 条" in text for text in detail["warnings"])

    def test_empty_list_yields_zero_tasks_success(self, client: TestClient, site: Any) -> None:
        """列表为空：0 任务 + success + 明确提示。"""
        site.chapters = []
        ds_id = support.create_source(client, site, name="空源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_SUCCESS
        assert detail["total_tasks"] == 0
        assert support.tasks_of(client, batch_id) == []
        assert detail["warnings"], "空列表必须给出用户可见提示"

    def test_phase_one_failure_keeps_cursor_and_creates_no_task(
        self, client: TestClient, site: Any
    ) -> None:
        """阶段一失败：批次 failed、无任务、游标不推进（PRD 7.4）。"""
        ds_id = support.create_source(client, site, name="坏列表源")
        site.status_overrides["/text/list.html"] = 500
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_FAILED
        assert detail["error_code"] == "4005"
        assert detail["total_tasks"] == 0
        assert support.tasks_of(client, batch_id) == []
        source = support.source_detail(client, ds_id)
        assert source["cursor_last_item_no"] == 0, "阶段一失败不得推进游标"

    def test_partial_failure_advances_cursor_to_last_success(
        self, client: TestClient, site: Any
    ) -> None:
        """部分失败：仅按成功项推进游标（末尾条目失败 → 游标停在 2）。"""
        site.chapters = site.chapters[:3]
        site.status_overrides["/text/3.html"] = 404
        ds_id = support.create_source(client, site, name="部分失败源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 3})
        detail = support.wait_batch(client, batch_id)

        assert detail["status"] == E.BATCH_SUCCESS_WITH_WARNING
        assert detail["done_tasks"] == 2
        assert detail["failed_tasks"] == 1
        assert support.source_detail(client, ds_id)["cursor_last_item_no"] == 2

        failed = [task for task in support.tasks_of(client, batch_id) if task["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["error_code"] == "4005"
        assert failed[0]["error_msg"], "失败任务必须有可读原因"


# ---------------------------------------------------------------------------
# 小说目录模板（脚本数据源提供 book 字段）
# ---------------------------------------------------------------------------
class TestNovelPathEndToEnd:
    """小说类：{root}/{数据源}/{分类}/{小说名}/{章节名}.txt。"""

    SCRIPT_TEMPLATE = """
def parse(args):
    if args["mode"] == "list":
        return {"items": [
            {"title": "第001章 科学边界", "url": "@BASE@/text/1.html",
             "date": "2026-10-20", "payload": {"book": "三体"}},
            {"title": "第002章 台球", "url": "@BASE@/text/2.html",
             "date": "2026-10-21", "payload": {"book": "三体"}}
        ], "pages": 1}
    item = args["item"]
    http_get(args["url"])
    return {"title": item["title"], "content": "正文内容：" + item["title"]}
"""

    def test_novel_directory_template(self, client: TestClient, site: Any) -> None:
        """脚本返回 book 字段时，产物落在 小说名 目录下。"""
        script = self.SCRIPT_TEMPLATE.replace("@BASE@", site.base_url)
        ds_id = int(
            support.unwrap(
                client.post(
                    "/api/data-sources",
                    json={
                        "name": "脚本小说网",
                        "type": E.TYPE_TEXT,
                        "category": "科幻",
                        "homepage_url": site.url("text/list.html"),
                        "script": script,
                        "script_entry": "parse",
                        "is_novel": True,
                        "enabled": True,
                    },
                )
            )["id"]
        )
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_SUCCESS, detail

        artifacts = support.artifacts_of(client, ds_id)
        assert len(artifacts) == 2
        expected = {
            OUTPUT_ROOT / "脚本小说网" / "科幻" / "三体" / "第001章 科学边界.txt",
            OUTPUT_ROOT / "脚本小说网" / "科幻" / "三体" / "第002章 台球.txt",
        }
        actual = {Path(artifact["path"]) for artifact in artifacts}
        assert actual == expected, f"小说目录模板不符：{actual}"
        for path in actual:
            assert path.stat().st_size > 0

    def test_novel_without_book_field_degrades(self, client: TestClient, site: Any) -> None:
        """内置解析器（无 book 字段）：小说每章各自成为一级目录（实现现状，记为观察项）。"""
        ds_id = support.create_source(client, site, name="无书名字典源", is_novel=True, category="科幻")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})
        support.wait_batch(client, batch_id)
        artifact = support.artifacts_of(client, ds_id)[0]
        path = Path(artifact["path"])
        assert path.exists()
        # 现状：{章节名}/{章节名}.txt —— 缺少「小说名」这一层（应为脚本提供 book 字段）
        assert path.parent.name == path.stem


# ---------------------------------------------------------------------------
# S2 / S3 端到端
# ---------------------------------------------------------------------------
class TestPageStrategyEndToEnd:
    """S2：起始页越界 → failed(3008)；页数越界 → 截断 + WARN。"""

    def test_start_page_out_of_range(self, client: TestClient, site: Any) -> None:
        """起始页超总页数：批次 failed，error_code=3008，无任务。"""
        ds_id = support.create_source(client, site, name="越界源", total_pages=2)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_PAGE, {"start": 9, "pages": 1})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_FAILED
        assert detail["error_code"] == "3008"
        assert detail["total_tasks"] == 0
        assert support.tasks_of(client, batch_id) == []

    def test_pages_truncated_to_last_page(self, client: TestClient, site: Any) -> None:
        """页数越界：截断到最后一页并 success_with_warning，游标停在最后一页。"""
        ds_id = support.create_source(client, site, name="截断源", total_pages=2)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_PAGE, {"start": 1, "pages": 9})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_SUCCESS_WITH_WARNING
        assert detail["total_tasks"] == 4, "2 页 × 每页 2 条"
        assert any("已到最后一页" in text for text in detail["warnings"])
        assert support.source_detail(client, ds_id)["cursor_last_page"] == 2


class TestDateStrategyEndToEnd:
    """S3：日期过滤 + 历史成功指纹去重（增量补采）。"""

    def test_date_range_and_dedupe_on_second_run(self, client: TestClient, site: Any) -> None:
        """首次按日期抓取；同日区间再次执行时全部命中历史指纹被跳过。"""
        ds_id = support.create_source(client, site, name="日期源", with_date=True)
        params = {"from": "2026-10-11", "to": "2026-10-12"}

        first = support.create_batch(client, ds_id, E.STRATEGY_DATE, params)
        first_detail = support.wait_batch(client, first)
        # 章节日期为 2026-10-11 / 10-12 → 命中 2 条
        assert first_detail["total_tasks"] == 2
        assert first_detail["done_tasks"] == 2

        second = support.create_batch(client, ds_id, E.STRATEGY_DATE, params)
        second_detail = support.wait_batch(client, second)
        assert second_detail["total_tasks"] == 0, "重复执行不应产生重复任务"
        assert second_detail["skipped_tasks"] == 2
        # PRD 7.2「任意策略：去重后任务数为 0 → 批次 success，任务数 0」
        assert second_detail["status"] == E.BATCH_SUCCESS
        assert len(support.artifacts_of(client, ds_id)) == 2, "产物不应重复"


# ---------------------------------------------------------------------------
# 图片链路
# ---------------------------------------------------------------------------
class TestImageEndToEnd:
    """图片：一个图集 = 一个任务，落盘 001/002/003.jpg。"""

    def test_gallery_downloaded_as_directory(self, client: TestClient, site: Any) -> None:
        """图集任务成功，产物为目录且按序号命名图片。"""
        ds_id = support.create_source(client, site, name="某图库", kind=E.TYPE_IMAGE, category="写真")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_SUCCESS, detail
        assert detail["total_tasks"] == 1

        artifact = support.artifacts_of(client, ds_id)[0]
        directory = Path(artifact["path"])
        assert directory.is_dir()
        assert artifact["type"] == E.ARTIFACT_IMAGE
        names = sorted(item.name for item in directory.iterdir())
        assert names == ["001.jpg", "002.jpg", "003.jpg"]
        assert all((directory / name).stat().st_size > 0 for name in names)
        assert artifact["size"] > 0

        task = support.tasks_of(client, batch_id)[0]
        assert task["image_count"] == 3


# ---------------------------------------------------------------------------
# 视频链路（环境限制：本机无 ffmpeg，验证降级 + DRM 两条路径）
# ---------------------------------------------------------------------------
class TestVideoEndToEnd:
    """视频：ffmpeg 缺失降级产物 3003；SAMPLE-AES 拒绝 4007。"""

    def test_degraded_ts_artifact_when_ffmpeg_missing(
        self,
        client: TestClient,
        site: Any,
        no_ffmpeg: None,
        ffmpeg_precheck_ok: None,
    ) -> None:
        """ffmpeg 缺失：任务 failed(3003)，但 .ts 产物真实存在且非空（PRD P0-10④）。"""
        ds_id = support.create_source(client, site, name="自测影视站", kind=E.TYPE_VIDEO)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        detail = support.wait_batch(client, batch_id)

        assert detail["status"] == E.BATCH_FAILED, detail
        assert detail["failed_tasks"] == 2

        tasks = support.tasks_of(client, batch_id)
        assert all(task["error_code"] == "3003" for task in tasks)
        assert all("ffmpeg" in (task["error_msg"] or "") for task in tasks)

        artifacts = support.artifacts_of(client, ds_id)
        assert len(artifacts) == 2
        for artifact in artifacts:
            path = Path(artifact["path"])
            assert path.suffix == ".ts"
            assert path.exists() and path.stat().st_size > 0
            assert artifact["status"] == E.ARTIFACT_FAILED

    def test_sample_aes_rejected_with_4007(
        self,
        client: TestClient,
        site: Any,
        no_ffmpeg: None,
        ffmpeg_precheck_ok: None,
    ) -> None:
        """SAMPLE-AES 流：任务失败且错误码 4007（DRM 不支持）。"""
        site.m3u8_mode = "sample_aes"
        ds_id = support.create_source(client, site, name="DRM影视站", kind=E.TYPE_VIDEO)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_FAILED
        task = support.tasks_of(client, batch_id)[0]
        assert task["error_code"] == "4007"
        assert task["status"] == E.TASK_FAILED

    def test_temp_dir_retained_after_failure(
        self, client: TestClient, site: Any, no_ffmpeg: None, ffmpeg_precheck_ok: None
    ) -> None:
        """降级失败保留临时目录便于排查（PRD 9.7：失败保留 24h）。"""
        ds_id = support.create_source(client, site, name="临时目录源", kind=E.TYPE_VIDEO)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})
        support.wait_batch(client, batch_id)
        temp_root = OUTPUT_ROOT / ".tmp"
        assert temp_root.exists(), "失败任务应保留 .tmp 便于排查（PRD 9.7）"
        assert any(item.is_dir() for item in temp_root.iterdir())


# ---------------------------------------------------------------------------
# 性能/一致性冒烟
# ---------------------------------------------------------------------------
def test_batch_list_and_task_list_consistent(client: TestClient, site: Any) -> None:
    """批次列表计数与任务列表实际条数一致（统计自洽）。"""
    ds_id = support.create_source(client, site, name="一致性源")
    batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 3})
    support.wait_batch(client, batch_id)

    listed = support.unwrap(client.get("/api/batches", params={"data_source_id": ds_id}))
    item = listed["items"][0]
    tasks = support.tasks_of(client, batch_id)
    assert item["total_tasks"] == len(tasks) == 3
    assert item["done_tasks"] == sum(1 for task in tasks if task["status"] == "success")


def test_elapsed_ms_is_non_negative(client: TestClient, site: Any) -> None:
    """批次耗时统计非负且 finished_at >= started_at。"""
    ds_id = support.create_source(client, site, name="耗时源")
    batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})
    detail = support.wait_batch(client, batch_id)
    assert detail["started_at"] and detail["finished_at"]
    assert detail["finished_at"] >= detail["started_at"]
    progress = support.unwrap(client.get(f"/api/batches/{batch_id}/progress"))
    assert progress["batch"]["elapsed_ms"] >= 0


def test_dashboard_trend_counts_today_success(client: TestClient, site: Any) -> None:
    """趋势接口 day 粒度的当日合计等于成功任务数。"""
    ds_id = support.create_source(client, site, name="趋势源")
    batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
    support.wait_batch(client, batch_id)
    trend = support.unwrap(client.get("/api/dashboard/trend", params={"granularity": "day"}))
    assert trend["granularity"] == "day"
    assert len(trend["points"]) == 24
    assert sum(point["count"] for point in trend["points"]) == 2
