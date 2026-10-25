"""并发约束：实测峰值并发不超过 max_threads；单条失败不阻断批次；SQLite 不锁库。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import support
from app.config import E
from conftest import wait_engine_idle


def grow(site: Any, count: int) -> None:
    """把模拟站点章节数扩到 ``count`` 条（每页 2 条 → 需要翻页补足）。"""
    site.chapters = [
        {"id": index, "title": f"第{index:03d}章 并发测试", "date": f"2026-10-{10 + index % 20:02d}"}
        for index in range(1, count + 1)
    ]


class TestConcurrencyLimit:
    """P0-15①：用 8 个慢任务 + 线程数 2 验证并发不超过配置值。"""

    def test_peak_concurrency_not_exceed_max_threads(self, client: TestClient, site: Any) -> None:
        """max_threads=2、8 个任务：站点侧观测到的任务级并发峰值 ≤ 2。"""
        grow(site, 8)
        site.delay = 0.2
        support.unwrap(client.put("/api/settings", json={"max_threads": 2}))
        ds_id = support.create_source(client, site, name="并发限制源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 8})
        detail = support.wait_batch(client, batch_id, timeout=180)

        assert detail["status"] == E.BATCH_SUCCESS
        assert detail["done_tasks"] == 8
        assert site.max_detail_inflight <= 2, (
            f"实测峰值并发 {site.max_detail_inflight} 超过 max_threads=2"
        )
        assert site.max_detail_inflight >= 2, "应真正并发执行（否则该断言无意义）"

    def test_global_limit_across_two_batches(self, client: TestClient, site: Any) -> None:
        """两个数据源并发采集：全局峰值并发仍 ≤ max_threads（§9.3）。"""
        grow(site, 8)
        site.delay = 0.2
        support.unwrap(client.put("/api/settings", json={"max_threads": 2}))
        ds_a = support.create_source(client, site, name="并发源甲")
        ds_b = support.create_source(client, site, name="并发源乙")
        batch_a = support.create_batch(client, ds_a, E.STRATEGY_COUNT, {"n": 4})
        batch_b = support.create_batch(client, ds_b, E.STRATEGY_COUNT, {"n": 4})

        support.wait_batch(client, batch_a, timeout=180)
        support.wait_batch(client, batch_b, timeout=180)

        assert site.max_detail_inflight <= 2, (
            f"两个批次合计峰值 {site.max_detail_inflight} 超过全局上限 2"
        )
        assert support.batch_detail(client, batch_a)["done_tasks"] == 4
        assert support.batch_detail(client, batch_b)["done_tasks"] == 4


class TestFailureIsolation:
    """NFR-06：单任务失败不影响批次其他任务。"""

    def test_one_404_among_eight_tasks_yields_warning(
        self, client: TestClient, site: Any
    ) -> None:
        """8 个任务里 1 个 404：其余 7 个成功，批次 success_with_warning。"""
        grow(site, 8)
        support.unwrap(client.put("/api/settings", json={"max_threads": 4}))
        site.status_overrides["/text/3.html"] = 404
        ds_id = support.create_source(client, site, name="失败隔离源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 8})
        detail = support.wait_batch(client, batch_id, timeout=180)

        assert detail["status"] == E.BATCH_SUCCESS_WITH_WARNING
        assert detail["done_tasks"] == 7
        assert detail["failed_tasks"] == 1
        assert site.max_detail_inflight <= 4

        failed = [task for task in support.tasks_of(client, batch_id) if task["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["error_code"] == "4005"
        assert failed[0]["attempt_count"] == 1, "404 属不可重试错误，不应重试"

    def test_500_detail_error_is_retried_then_failed(
        self, client: TestClient, site: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5xx 属可重试错误：重试到上限后失败，attempt_count 递增（PRD 9.5）。"""
        grow(site, 2)
        support.unwrap(client.put("/api/settings", json={"max_threads": 2}))
        site.status_overrides["/text/1.html"] = 500
        ds_id = support.create_source(client, site, name="重试源", total_pages=1)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 2})
        detail = support.wait_batch(client, batch_id, timeout=180)

        assert detail["status"] == E.BATCH_SUCCESS_WITH_WARNING
        tasks = support.tasks_of(client, batch_id)
        retried = [task for task in tasks if task["status"] == "failed"]
        assert len(retried) == 1
        assert retried[0]["attempt_count"] == 3, "默认 max_attempts=3，应执行 3 次"


class TestSqliteUnderLoad:
    """NFR-08：高并发写库不得出现 database is locked。"""

    def test_twenty_tasks_with_eight_threads_no_db_lock(
        self, client: TestClient, site: Any
    ) -> None:
        """max_threads=8、20 个任务：全部成功且日志无 database is locked。"""
        grow(site, 20)
        support.unwrap(client.put("/api/settings", json={"max_threads": 8}))
        ds_id = support.create_source(client, site, name="压测源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 20})
        detail = support.wait_batch(client, batch_id, timeout=300)

        assert detail["status"] == E.BATCH_SUCCESS, detail
        assert detail["done_tasks"] == 20
        assert detail["failed_tasks"] == 0
        assert site.max_detail_inflight <= 8, (
            f"峰值并发 {site.max_detail_inflight} 超过 max_threads=8"
        )

        logs = support.unwrap(
            client.get(f"/api/batches/{batch_id}/logs", params={"pageSize": 1000})
        )
        messages = " ".join(item["message"] for item in logs["items"]).lower()
        assert "database is locked" not in messages
        assert "locked" not in messages
        tasks = support.tasks_of(client, batch_id, page_size=100)
        assert len(tasks) == 20
        assert all(task["error_code"] is None for task in tasks)


class TestEngineBookkeeping:
    """引擎计数与线程占用一致（首页系统信息口径）。"""

    def test_active_threads_back_to_zero_after_batch(
        self, client: TestClient, site: Any
    ) -> None:
        """批次结束后活跃线程回落到 0，且不超过配置上限。"""
        grow(site, 4)
        support.unwrap(client.put("/api/settings", json={"max_threads": 3}))
        ds_id = support.create_source(client, site, name="线程计数源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 4})
        support.wait_batch(client, batch_id, timeout=180)

        metrics = support.unwrap(client.get("/api/system/metrics"))
        assert metrics["threads"]["max"] == 3
        assert metrics["threads"]["active"] == 0, "批次结束后活跃线程必须归零"
        assert metrics["memory"]["total"] > 0
        assert 0 <= metrics["cpu_percent"] <= 100 * 2  # psutil 可能 >100（多核）


class TestSingleFlightRace:
    """数据源级 single-flight 在并发请求下仍然成立（PRD P0-15③ / §9.3）。"""

    THREADS = 4
    ROUNDS = 3

    def test_concurrent_create_same_source_only_one_succeeds(
        self, client: TestClient, site: Any
    ) -> None:
        """4 个线程同时为同一数据源建批次：只允许一个成功，其余 3001。"""
        import threading

        from app.common.errors import BizError
        from app.db.base import session_scope
        from app.schemas.batch import BatchCreate
        from app.services import batch_service

        ds_id = support.create_source(client, site, name="单飞竞态源")
        violations: list[str] = []
        created_total = 0

        for round_no in range(self.ROUNDS):
            barrier = threading.Barrier(self.THREADS)
            outcomes: list[str] = []
            lock = threading.Lock()

            def create_once() -> None:
                barrier.wait()
                try:
                    with session_scope() as db:
                        batch_service.create(
                            db,
                            BatchCreate(
                                data_source_id=ds_id,
                                strategy=E.STRATEGY_COUNT,
                                strategy_params={"n": 1},
                            ),
                        )
                    tag = "created"
                except BizError as exc:
                    tag = f"rejected:{exc.code}"
                except Exception as exc:  # noqa: BLE001
                    tag = f"error:{type(exc).__name__}"
                with lock:
                    outcomes.append(tag)

            threads = [threading.Thread(target=create_once) for _ in range(self.THREADS)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            created = outcomes.count("created")
            created_total += created
            if created > 1:
                violations.append(f"round{round_no}:{sorted(outcomes)}")
            rejected = [tag for tag in outcomes if tag != "created"]
            if rejected:
                unexpected = [tag for tag in rejected if tag != "rejected:3001"]
                assert not unexpected, (
                    "并发单飞被拒时必须统一返回 3001（不得泄漏 IntegrityError/5000）："
                    f"{sorted(outcomes)}"
                )
            wait_engine_idle(timeout=60)
            if violations:
                break

        assert not violations, (
            "single-flight 竞态：同一数据源被并发创建了多个活跃批次 " f"{violations}"
        )
        assert created_total >= 1, "至少有一轮应成功建批次（否则该用例失去意义）"
