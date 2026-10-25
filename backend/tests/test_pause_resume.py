"""暂停 / 恢复语义：不丢任务、不重复计数、进度接口状态正确（PRD 9.4）。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import support
from app.config import E


def grow_chapters(site: Any, count: int) -> None:
    """把模拟站点章节数扩到 ``count`` 条（每页 2 条）。"""
    site.chapters = [
        {"id": index, "title": f"第{index:03d}章 暂停测试", "date": f"2026-10-{10 + index % 20:02d}"}
        for index in range(1, count + 1)
    ]


def wait_until_started(client: TestClient, batch_id: int, done_at_least: int = 1) -> dict[str, Any]:
    """等待批次至少完成 ``done_at_least`` 条任务（确保暂停发生在执行中途）。"""
    deadline = time.time() + 30
    detail = support.batch_detail(client, batch_id)
    while time.time() < deadline:
        detail = support.batch_detail(client, batch_id)
        if detail["done_tasks"] >= done_at_least:
            return detail
        if detail["status"] in support.TERMINAL:
            return detail
        time.sleep(0.02)
    return detail


class TestPauseResume:
    """暂停 → 任务回退 pending → 恢复 → 全部完成且不丢/不重复。"""

    def test_pause_then_resume_completes_all_tasks(
        self, client: TestClient, site: Any
    ) -> None:
        """执行中途暂停，恢复后 6 条任务全部成功且产物唯一。"""
        grow_chapters(site, 6)
        site.delay = 0.15
        support.unwrap(client.put("/api/settings", json={"max_threads": 2}))
        ds_id = support.create_source(client, site, name="暂停恢复源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 6})

        wait_until_started(client, batch_id, done_at_least=1)
        paused = support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))
        assert paused["status"] == E.BATCH_PAUSED

        # 暂停收尾：批内不允许残留 running 任务
        deadline = time.time() + 30
        tasks: list[dict[str, Any]] = []
        while time.time() < deadline:
            tasks = support.tasks_of(client, batch_id)
            if not any(task["status"] == E.TASK_RUNNING for task in tasks):
                break
            time.sleep(0.05)
        assert not any(task["status"] == E.TASK_RUNNING for task in tasks), "暂停后不应残留 running 任务"
        assert len(tasks) == 6, "暂停不得丢任务"

        done_before = sum(1 for task in tasks if task["status"] == E.TASK_SUCCESS)
        pending_before = sum(1 for task in tasks if task["status"] == E.TASK_PENDING)
        detail = support.batch_detail(client, batch_id)
        assert detail["status"] in (E.BATCH_PAUSED, E.BATCH_PAUSED_WITH_WARNING)
        assert done_before + pending_before == 6, "已完成 + 待执行 应等于任务总数"
        assert detail["done_tasks"] == done_before, "暂停期间 done_tasks 必须等于实际成功数"

        # 恢复并等待终态
        assert support.unwrap(client.post(f"/api/batches/{batch_id}/resume"))["status"] == "running"
        final = support.wait_batch(client, batch_id, timeout=120)
        assert final["status"] == E.BATCH_SUCCESS, final
        assert final["done_tasks"] == 6, "恢复后必须补齐全部任务"
        assert final["failed_tasks"] == 0
        assert final["progress"] == 100

        tasks = support.tasks_of(client, batch_id)
        assert all(task["status"] == E.TASK_SUCCESS for task in tasks)
        assert sum(task["attempt_count"] for task in tasks) >= 6

        artifacts = support.artifacts_of(client, ds_id)
        paths = [artifact["path"] for artifact in artifacts]
        assert len(paths) == 6, f"产物数量必须等于任务数（无重复计数）：{paths}"
        assert len(set(paths)) == 6, "同一任务不得产出多份产物"
        for artifact in artifacts:
            assert Path(artifact["path"]).exists()
            assert artifact["status"] == E.ARTIFACT_SUCCESS

    def test_progress_status_during_pause(self, client: TestClient, site: Any) -> None:
        """暂停期间进度接口的批次状态为 paused、活跃任务为空。"""
        grow_chapters(site, 4)
        site.delay = 0.2
        support.unwrap(client.put("/api/settings", json={"max_threads": 1}))
        ds_id = support.create_source(client, site, name="暂停进度源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 4})

        wait_until_started(client, batch_id, done_at_least=1)
        support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))

        deadline = time.time() + 30
        progress: dict[str, Any] = {}
        while time.time() < deadline:
            progress = support.unwrap(client.get(f"/api/batches/{batch_id}/progress"))
            if progress["batch"]["status"] != E.BATCH_RUNNING and not progress["active"]:
                break
            time.sleep(0.05)
        assert progress["batch"]["status"] == E.BATCH_PAUSED
        assert progress["active"] == [], "暂停收尾后 active 列表必须为空"
        assert progress["batch"]["total"] == 4
        assert progress["batch"]["failed"] == 0

        # 恢复后能继续
        support.unwrap(client.post(f"/api/batches/{batch_id}/resume"))
        assert support.wait_batch(client, batch_id, timeout=120)["status"] == E.BATCH_SUCCESS

    def test_pause_before_first_task_keeps_everything_pending(
        self, client: TestClient, site: Any
    ) -> None:
        """阶段一刚建完任务即暂停：全部任务保持 pending，恢复后仍可完成。"""
        grow_chapters(site, 3)
        site.delay = 0.3
        support.unwrap(client.put("/api/settings", json={"max_threads": 1}))
        ds_id = support.create_source(client, site, name="早期暂停源")
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 3})

        # 阶段一（列表解析）完成、阶段二刚开始时立刻暂停
        deadline = time.time() + 30
        while time.time() < deadline:
            detail = support.batch_detail(client, batch_id)
            if detail["total_tasks"] == 3:
                break
            time.sleep(0.02)
        support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))
        time.sleep(0.5)

        tasks = support.tasks_of(client, batch_id)
        assert len(tasks) == 3
        assert not any(task["status"] == E.TASK_RUNNING for task in tasks)

        support.unwrap(client.post(f"/api/batches/{batch_id}/resume"))
        final = support.wait_batch(client, batch_id, timeout=120)
        assert final["done_tasks"] == 3
        assert len(support.artifacts_of(client, ds_id)) == 3, "产物不得重复"

    def test_pause_during_gallery_does_not_duplicate_artifact_rows(
        self, client: TestClient, site: Any
    ) -> None:
        """图集任务在「每张图」粒度的检查点被暂停后恢复：同一任务只应有一条产物记录。"""
        site.galleries = [{"id": 1, "title": "慢图集", "date": "2026-10-20", "images": 4}]
        site.image_delay = 0.8
        support.unwrap(client.put("/api/settings", json={"max_threads": 1}))
        ds_id = support.create_source(client, site, name="产物唯一性源", kind=E.TYPE_IMAGE)
        batch_id = support.create_batch(client, ds_id, E.STRATEGY_COUNT, {"n": 1})

        # 等到图集任务确实在下图（此时已登记 processing 产物），再请求暂停
        deadline = time.time() + 40
        while time.time() < deadline:
            progress = support.unwrap(client.get(f"/api/batches/{batch_id}/progress"))
            if progress["active"] and progress["active"][0]["step_done"] >= 1:
                break
            time.sleep(0.05)
        support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))

        while time.time() < deadline:
            if not any(t["status"] == E.TASK_RUNNING for t in support.tasks_of(client, batch_id)):
                break
            time.sleep(0.05)
        reverted = support.tasks_of(client, batch_id)[0]
        assert reverted["status"] == E.TASK_PENDING, "图片任务应在原子步骤（单图）结束后回退 pending"

        support.unwrap(client.post(f"/api/batches/{batch_id}/resume"))
        final = support.wait_batch(client, batch_id, timeout=180)
        assert final["done_tasks"] == 1

        artifacts = support.artifacts_of(client, ds_id)
        assert len(artifacts) == 1, (
            "同一任务并存了多条产物记录："
            f"{[(a['id'], a['status'], a['path']) for a in artifacts]}"
        )
