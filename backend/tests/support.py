"""测试辅助函数（供各测试模块复用，不含断言逻辑本身）。"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from app.config import E

TERMINAL = set(E.BATCH_TERMINAL_STATUSES)


# ---------------------------------------------------------------------------
# 响应解包
# ---------------------------------------------------------------------------
def unwrap(response: Any, expected_code: int = 0) -> Any:
    """校验统一响应信封并返回 ``data``。"""
    payload = response.json()
    assert set(payload) == {"code", "data", "message"}, f"响应信封字段不符：{payload}"
    assert payload["code"] == expected_code, (
        f"期望业务码 {expected_code}，实际 {payload['code']}：{payload['message']}"
    )
    if expected_code != 0:
        assert payload["data"] is None, f"失败响应 data 必须为 None：{payload}"
    return payload["data"]


# ---------------------------------------------------------------------------
# 站点配置
# ---------------------------------------------------------------------------
def list_config(
    site: Any,
    kind: str,
    *,
    total_pages: int | None = None,
    with_date: bool = False,
) -> dict[str, Any]:
    """构造内置解析器的 ``config_json``（指向离线模拟站点）。"""
    config: dict[str, Any] = {
        "list_url": f"{site.base_url}/{kind}/list.html?page={{page}}",
        "item_selector": ".list li",
        "link_selector": "a@href",
        "title_selector": "a@text",
        "max_pages": 20,
    }
    if kind == E.TYPE_TEXT:
        config["detail_content_selector"] = "#content"
    elif kind == E.TYPE_IMAGE:
        config["detail_image_selector"] = ".gallery img@src"
    elif kind == E.TYPE_VIDEO:
        config["detail_video_selector"] = "video@src"
    if with_date:
        config["date_selector"] = ".date@text"
    if total_pages is not None:
        config["total_pages"] = total_pages
    return config


# ---------------------------------------------------------------------------
# 数据源 / 批次
# ---------------------------------------------------------------------------
def create_source(
    client: TestClient,
    site: Any,
    *,
    name: str,
    kind: str = E.TYPE_TEXT,
    category: str = "测试分类",
    is_novel: bool = False,
    total_pages: int | None = None,
    with_date: bool = False,
    enabled: bool = True,
    config: dict[str, Any] | None = None,
) -> int:
    """通过 API 创建数据源，返回 id。"""
    payload = {
        "name": name,
        "type": kind,
        "category": category,
        "homepage_url": site.url(f"{kind}/list.html"),
        "config_json": config or list_config(site, kind, total_pages=total_pages, with_date=with_date),
        "is_novel": is_novel,
        "enabled": enabled,
    }
    return int(unwrap(client.post("/api/data-sources", json=payload))["id"])


def create_batch(
    client: TestClient,
    ds_id: int,
    strategy: str,
    params: dict[str, Any],
    *,
    export_format: str | None = None,
) -> int:
    """通过 API 创建批次，返回 batch_id。"""
    body: dict[str, Any] = {
        "data_source_id": int(ds_id),
        "strategy": strategy,
        "strategy_params": params,
    }
    if export_format:
        body["export_format"] = export_format
    return int(unwrap(client.post("/api/batches", json=body))["batch_id"])


def batch_detail(client: TestClient, batch_id: int) -> dict[str, Any]:
    """读取批次详情。"""
    return unwrap(client.get(f"/api/batches/{batch_id}"))


def wait_batch(client: TestClient, batch_id: int, timeout: float = 90.0) -> dict[str, Any]:
    """轮询直到批次进入终态，返回详情。"""
    deadline = time.time() + timeout
    detail = batch_detail(client, batch_id)
    while time.time() < deadline:
        detail = batch_detail(client, batch_id)
        if detail["status"] in TERMINAL:
            return detail
        time.sleep(0.1)
    raise AssertionError(f"批次 {batch_id} 未在 {timeout}s 内到达终态：{detail}")


def wait_status(
    client: TestClient, batch_id: int, statuses: set[str], timeout: float = 30.0
) -> dict[str, Any]:
    """轮询直到批次状态落入给定集合。"""
    deadline = time.time() + timeout
    detail = batch_detail(client, batch_id)
    while time.time() < deadline:
        detail = batch_detail(client, batch_id)
        if detail["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"批次 {batch_id} 未在 {timeout}s 内进入 {statuses}：{detail}")


def tasks_of(client: TestClient, batch_id: int, page_size: int = 100) -> list[dict[str, Any]]:
    """列出批次内全部任务（按 seq_no 升序）。"""
    data = unwrap(client.get("/api/tasks", params={"batch_id": batch_id, "pageSize": page_size}))
    return data["items"]


def artifacts_of(client: TestClient, ds_id: int, page_size: int = 100) -> list[dict[str, Any]]:
    """列出某数据源的全部产物。"""
    data = unwrap(
        client.get("/api/artifacts", params={"data_source_id": ds_id, "pageSize": page_size})
    )
    return data["items"]


def source_detail(client: TestClient, ds_id: int) -> dict[str, Any]:
    """读取数据源详情（含游标三字段）。"""
    return unwrap(client.get(f"/api/data-sources/{ds_id}"))


def as_setting(client: TestClient, **fields: Any) -> dict[str, Any]:
    """更新设置并返回最新全量设置。"""
    return unwrap(client.put("/api/settings", json=fields))


# ---------------------------------------------------------------------------
# 状态播种（直接落库，避免异步执行带来的竞态）
# ---------------------------------------------------------------------------
def insert_batch(
    ds_id: int,
    *,
    status: str,
    phase: str = E.PHASE_DONE,
    strategy: str = E.STRATEGY_COUNT,
    total: int = 0,
    done: int = 0,
    failed: int = 0,
    threads: int = 2,
) -> int:
    """插入一条指定状态的批次记录。"""
    from app.db.base import session_scope
    from app.db.models import CrawlBatch

    with session_scope() as db:
        batch = CrawlBatch(
            data_source_id=int(ds_id),
            strategy=strategy,
            strategy_params={"n": 1},
            status=status,
            phase=phase,
            total_tasks=int(total),
            done_tasks=int(done),
            failed_tasks=int(failed),
            skipped_tasks=0,
            threads=int(threads),
            request_url="http://fake.test/list",
            warnings=[],
        )
        db.add(batch)
        db.flush()
        return int(batch.id)


def insert_task(
    batch_id: int,
    ds_id: int,
    *,
    status: str = E.TASK_PENDING,
    seq: int = 1,
    title: str = "任务1",
    url: str | None = None,
    attempt_count: int = 0,
    error_code: str | None = None,
) -> int:
    """插入一条指定状态的任务记录。"""
    from app.db.base import session_scope
    from app.db.models import CrawlTask

    with session_scope() as db:
        task = CrawlTask(
            batch_id=int(batch_id),
            data_source_id=int(ds_id),
            seq_no=int(seq),
            title=title,
            source_url=url or f"http://fake.test/detail/{seq}",
            payload={},
            status=status,
            attempt_count=int(attempt_count),
            error_code=error_code,
            step_total=1,
            step_done=0,
        )
        db.add(task)
        db.flush()
        return int(task.id)


def insert_artifact(
    ds_id: int,
    task_id: int,
    *,
    status: str = E.ARTIFACT_SUCCESS,
    art_type: str = E.ARTIFACT_TEXT,
    name: str = "任务1",
    path: str = "",
    size: int = 0,
    error_msg: str | None = None,
) -> int:
    """插入一条指定状态的产物记录。"""
    from app.db.base import session_scope
    from app.db.models import Artifact

    with session_scope() as db:
        artifact = Artifact(
            task_id=int(task_id),
            task_result_id=None,
            data_source_id=int(ds_id),
            data_source_name="契约源",
            type=art_type,
            name=name,
            category="测试分类",
            path=path,
            size=int(size),
            status=status,
            error_msg=error_msg,
        )
        db.add(artifact)
        db.flush()
        return int(artifact.id)
