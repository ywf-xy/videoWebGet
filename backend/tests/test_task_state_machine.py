"""批次 / 任务状态机：非法跃迁必须被拒（PRD 9.4 / 9.5、架构 §4.3-4.4 错误码）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import support
from app.common.errors import ErrCode
from app.config import E
from support import insert_batch, insert_task


@pytest.fixture
def ds(client: TestClient, site: Any) -> int:
    """状态机用例共用数据源。"""
    return support.create_source(client, site, name="状态机源")


def code_of(response: Any) -> int:
    """读取业务码。"""
    return int(response.json()["code"])


# ---------------------------------------------------------------------------
# 批次状态机
# ---------------------------------------------------------------------------
class TestBatchStateMachine:
    """批次：终态不可暂停、仅 paused 可恢复、单飞约束。"""

    @pytest.mark.parametrize(
        "status",
        [E.BATCH_SUCCESS, E.BATCH_SUCCESS_WITH_WARNING, E.BATCH_FAILED, E.BATCH_PAUSED],
    )
    def test_terminal_batch_cannot_be_paused(self, client: TestClient, ds: int, status: str) -> None:
        """终态（含已暂停）批次不可再暂停 → 3005。"""
        batch_id = insert_batch(ds, status=status)
        response = client.post(f"/api/batches/{batch_id}/pause")
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.BATCH_STATE_INVALID) == 3005

    def test_pending_batch_can_be_paused(self, client: TestClient, ds: int) -> None:
        """pending 批次可暂停 → paused。"""
        batch_id = insert_batch(ds, status=E.BATCH_PENDING, phase=E.PHASE_PARSE)
        data = support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))
        assert data["status"] == E.BATCH_PAUSED
        assert support.batch_detail(client, batch_id)["status"] == E.BATCH_PAUSED

    @pytest.mark.parametrize("status", [E.BATCH_RUNNING, E.BATCH_SUCCESS, E.BATCH_PENDING])
    def test_non_paused_batch_cannot_be_resumed(
        self, client: TestClient, ds: int, status: str
    ) -> None:
        """仅 paused / paused_with_warning 可恢复，其余 → 3005。"""
        batch_id = insert_batch(ds, status=status, phase=E.PHASE_EXECUTE)
        response = client.post(f"/api/batches/{batch_id}/resume")
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.BATCH_STATE_INVALID)

    def test_batch_not_found_returns_3004(self, client: TestClient) -> None:
        """批次不存在 → 3004（详情/进度/暂停/恢复/重试/日志统一）。"""
        for method, path in (
            ("get", "/api/batches/999999"),
            ("get", "/api/batches/999999/progress"),
            ("get", "/api/batches/999999/logs"),
            ("post", "/api/batches/999999/pause"),
            ("post", "/api/batches/999999/resume"),
            ("post", "/api/batches/999999/retry-failed"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 404, f"{path} 应返回 404"
            assert code_of(response) == int(ErrCode.BATCH_NOT_FOUND) == 3004

    @pytest.mark.parametrize("busy_status", list(E.BATCH_BUSY_STATUSES))
    def test_single_flight_rejects_second_batch(
        self, client: TestClient, ds: int, busy_status: str
    ) -> None:
        """同数据源存在 pending/running/paused 批次时拒绝新批次 → 3001。"""
        insert_batch(ds, status=busy_status, phase=E.PHASE_PARSE)
        response = client.post(
            "/api/batches",
            json={"data_source_id": ds, "strategy": "count", "strategy_params": {"n": 1}},
        )
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.BATCH_SINGLE_FLIGHT) == 3001

    def test_terminal_batch_does_not_block_new_batch(self, client: TestClient, ds: int, site: Any) -> None:
        """上一个批次已终态：允许再次发起（单飞只约束活跃批次）。"""
        insert_batch(ds, status=E.BATCH_SUCCESS, done=1, total=1)
        batch_id = support.create_batch(client, ds, E.STRATEGY_COUNT, {"n": 1})
        assert isinstance(batch_id, int) and batch_id > 0


# ---------------------------------------------------------------------------
# 任务状态机
# ---------------------------------------------------------------------------
class TestTaskStateMachine:
    """任务：仅 failed 可重试；批量重试无可重试项 → 3006。"""

    @pytest.mark.parametrize(
        "status",
        [E.TASK_SUCCESS, E.TASK_PENDING, E.TASK_RUNNING, E.TASK_SKIPPED, E.TASK_PAUSED],
    )
    def test_only_failed_task_is_retryable(
        self, client: TestClient, ds: int, status: str
    ) -> None:
        """非 failed 状态任务重试 → 3007。"""
        batch_id = insert_batch(ds, status=E.BATCH_SUCCESS, total=1, done=1)
        task_id = insert_task(batch_id, ds, status=status)
        response = client.post(f"/api/tasks/{task_id}/retry")
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.TASK_NOT_RETRYABLE) == 3007

    def test_failed_task_retry_returns_to_pending(self, client: TestClient, ds: int, site: Any) -> None:
        """failed 任务重试：接受请求，且 attempt_count 不清零（PRD 9.5）。"""
        batch_id = insert_batch(ds, status=E.BATCH_SUCCESS_WITH_WARNING, total=1, failed=1)
        task_id = insert_task(
            batch_id,
            ds,
            status=E.TASK_FAILED,
            url=site.url("text/1.html"),
            attempt_count=2,
        )
        data = support.unwrap(client.post(f"/api/tasks/{task_id}/retry"))
        # 任务可能已被执行体领取（running）或仍在队列（pending），二者均为合法跃迁
        assert data["status"] in (E.TASK_PENDING, E.TASK_RUNNING)
        assert data["attempt_count"] >= 2, "手动重试不得清零 attempt_count"

    def test_task_not_found_returns_4003(self, client: TestClient) -> None:
        """任务不存在 → 4003（详情/日志/重试）。"""
        for method, path in (
            ("get", "/api/tasks/999999"),
            ("get", "/api/tasks/999999/logs"),
            ("post", "/api/tasks/999999/retry"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 404
            assert code_of(response) == int(ErrCode.TASK_NOT_FOUND) == 4003

    def test_batch_retry_failed_without_failed_tasks_returns_3006(
        self, client: TestClient, ds: int
    ) -> None:
        """批次内没有 failed 任务 → 3006 NOTHING_TO_RETRY。"""
        batch_id = insert_batch(ds, status=E.BATCH_SUCCESS, total=1, done=1)
        insert_task(batch_id, ds, status=E.TASK_SUCCESS)
        response = client.post(f"/api/batches/{batch_id}/retry-failed")
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.NOTHING_TO_RETRY) == 3006

    def test_batch_retry_failed_submits_count(self, client: TestClient, ds: int, site: Any) -> None:
        """批量重试返回已提交条数（= failed 任务数）。"""
        batch_id = insert_batch(ds, status=E.BATCH_SUCCESS_WITH_WARNING, total=2, failed=2)
        for seq in (1, 2):
            insert_task(
                batch_id, ds, status=E.TASK_FAILED, seq=seq, url=site.url(f"text/{seq}.html")
            )
        data = support.unwrap(client.post(f"/api/batches/{batch_id}/retry-failed"))
        assert data["submitted"] == 2

    def test_retry_many_rejects_all_non_retryable(self, client: TestClient, ds: int) -> None:
        """批量重试所选任务全部不可重试 → 3007。"""
        batch_id = insert_batch(ds, status=E.BATCH_SUCCESS, total=1, done=1)
        task_id = insert_task(batch_id, ds, status=E.TASK_SUCCESS)
        response = client.post("/api/tasks/retry", json={"task_ids": [task_id]})
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.TASK_NOT_RETRYABLE)

    def test_paused_batch_keeps_tasks_pending(self, client: TestClient, ds: int) -> None:
        """批次暂停时立即变 paused，且任务仍是 pending（未被调度）。"""
        batch_id = insert_batch(ds, status=E.BATCH_PENDING, phase=E.PHASE_PARSE)
        for seq in (1, 2):
            insert_task(batch_id, ds, status=E.TASK_PENDING, seq=seq)
        support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))
        tasks = support.tasks_of(client, batch_id)
        assert all(task["status"] == E.TASK_PENDING for task in tasks)
        assert support.batch_detail(client, batch_id)["status"] == E.BATCH_PAUSED


# ---------------------------------------------------------------------------
# 数据源删除约束
# ---------------------------------------------------------------------------
class TestDataSourceBusy:
    """数据源被运行中批次引用时不可删除 → 2003；软删除后 2001。"""

    def test_delete_blocked_by_running_batch(self, client: TestClient, ds: int) -> None:
        """存在 running 批次 → 2003 DS_BUSY。"""
        insert_batch(ds, status=E.BATCH_RUNNING, phase=E.PHASE_EXECUTE)
        response = client.delete(f"/api/data-sources/{ds}")
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.DS_BUSY) == 2003

    def test_soft_delete_then_detail_not_found(self, client: TestClient, ds: int) -> None:
        """无活跃批次：软删除成功，随后详情返回 2001。"""
        assert support.unwrap(client.delete(f"/api/data-sources/{ds}"))["deleted"] == 1
        response = client.get(f"/api/data-sources/{ds}")
        assert response.status_code == 404
        assert code_of(response) == int(ErrCode.DS_NOT_FOUND) == 2001

    def test_disabled_source_rejected_for_new_batch(self, client: TestClient, site: Any) -> None:
        """停用数据源不允许发起采集 → 1001。"""
        ds_id = support.create_source(client, site, name="停用源", enabled=False)
        response = client.post(
            "/api/batches",
            json={"data_source_id": ds_id, "strategy": "count", "strategy_params": {"n": 1}},
        )
        assert response.status_code == 400
        assert code_of(response) == int(ErrCode.PARAM_INVALID)


# ---------------------------------------------------------------------------
# 第 2 轮回归补充：single-flight 数据库约束引入后的连带语义
# ---------------------------------------------------------------------------
class TestRetrySingleFlight:
    """重试历史终态批次会「复活」批次，必须同样受 single-flight 约束（P0-15③）。"""

    def test_retry_rejected_when_another_batch_is_active(
        self, client: TestClient, site: Any
    ) -> None:
        """同数据源已有活跃批次时重试历史失败批次 → 3001，且不改动任何状态。"""
        ds_id = support.create_source(client, site, name="重试冲突源")
        old_batch = insert_batch(ds_id, status=E.BATCH_FAILED, total=1, failed=1)
        task_id = support.insert_task(
            old_batch,
            ds_id,
            status=E.TASK_FAILED,
            url=site.url("text/1.html"),
            error_code="4005",
        )
        support.insert_artifact(ds_id, task_id, status=E.ARTIFACT_FAILED)

        # 另一个活跃批次（模拟用户已重新发起一次采集）
        active_batch = insert_batch(ds_id, status=E.BATCH_RUNNING, phase=E.PHASE_EXECUTE)

        response = client.post(f"/api/tasks/{task_id}/retry")
        assert response.status_code == 409
        assert code_of(response) == int(ErrCode.BATCH_SINGLE_FLIGHT) == 3001

        # 事务必须整体回滚：任务仍 failed、两个批次状态不变
        task = support.unwrap(client.get(f"/api/tasks/{task_id}"))
        assert task["status"] == E.TASK_FAILED, "被拒绝的重试不得留下半成品状态"
        assert support.batch_detail(client, old_batch)["status"] == E.BATCH_FAILED
        assert support.batch_detail(client, active_batch)["status"] == E.BATCH_RUNNING

    def test_retry_allowed_after_active_batch_finishes(
        self, client: TestClient, site: Any
    ) -> None:
        """活跃批次结束后，历史失败批次可正常重试并跑完。"""
        ds_id = support.create_source(client, site, name="重试恢复源")
        old_batch = insert_batch(ds_id, status=E.BATCH_SUCCESS_WITH_WARNING, total=1, failed=1)
        task_id = support.insert_task(
            old_batch, ds_id, status=E.TASK_FAILED, url=site.url("text/1.html")
        )
        insert_batch(ds_id, status=E.BATCH_FAILED, phase=E.PHASE_DONE)

        data = support.unwrap(client.post(f"/api/tasks/{task_id}/retry"))
        assert data["status"] in (E.TASK_PENDING, E.TASK_RUNNING)
        final = support.wait_batch(client, old_batch, timeout=120)
        assert final["status"] == E.BATCH_SUCCESS
        assert final["done_tasks"] == 1


class TestRetryArtifactReuse:
    """重试复用同一 artifact 记录（BUG-03 修复的另一个入口）。"""

    def test_retry_failed_task_keeps_single_artifact_row(
        self, client: TestClient, site: Any
    ) -> None:
        """failed 任务重试成功后，该任务仍只有 1 条产物记录，且状态转为 success。"""
        ds_id = support.create_source(client, site, name="重试产物源")
        batch_id = insert_batch(ds_id, status=E.BATCH_SUCCESS_WITH_WARNING, total=1, failed=1)
        task_id = support.insert_task(
            batch_id,
            ds_id,
            status=E.TASK_FAILED,
            url=site.url("text/1.html"),
            attempt_count=1,
            error_code="4005",
        )
        support.insert_artifact(
            ds_id, task_id, status=E.ARTIFACT_FAILED, error_msg="上一次失败"
        )

        support.unwrap(client.post(f"/api/tasks/{task_id}/retry"))
        final = support.wait_batch(client, batch_id, timeout=120)
        assert final["status"] == E.BATCH_SUCCESS
        assert final["done_tasks"] == 1

        artifacts = [item for item in support.artifacts_of(client, ds_id) if item["task_id"] == task_id]
        assert len(artifacts) == 1, f"重试后同一任务并存多条产物：{artifacts}"
        assert artifacts[0]["status"] == E.ARTIFACT_SUCCESS
        assert artifacts[0]["path"] and Path(artifacts[0]["path"]).exists()
        detail = support.unwrap(client.get(f"/api/artifacts/{artifacts[0]['id']}"))
        assert detail["error_msg"] is None, "成功后必须清空上一次的失败原因"
