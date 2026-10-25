"""API 契约断言：统一信封 / 分页 / 错误码分段 / snake_case / ISO8601 / pageSize 边界。

覆盖 43 个端点中的 40 个（未覆盖：头像上传的成功分支——会写入项目 static 目录，
只覆盖其失败分支；`/api/batches/{id}/logs` 与 `/api/tasks/{id}/logs` 的过滤参数另有专项）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

import support
from app.common.errors import ErrCode
from app.config import E
from support import insert_artifact, insert_batch, insert_task

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$")
CAMEL_RE = re.compile(r"^[a-z]+[A-Za-z]*$")

SCRIPT_OK = """
def parse(args):
    items = []
    for index in range(3):
        items.append({"title": "样例" + str(index), "url": "http://a.test/" + str(index)})
    return {"items": items, "pages": 2}
"""

SCRIPT_SYNTAX_ERROR = "def parse(args)\n    return {}\n"


# ---------------------------------------------------------------------------
# 公共装置与工具
# ---------------------------------------------------------------------------
@pytest.fixture
def seeded(client: TestClient, site: Any) -> dict[str, int]:
    """播种数据源 / 批次 / 任务 / 产物各一条，供 200 分支契约断言。"""
    ds_id = support.create_source(client, site, name="契约源", total_pages=2, with_date=True)
    batch_id = insert_batch(ds_id, status=E.BATCH_SUCCESS, total=1, done=1)
    task_id = insert_task(batch_id, ds_id, status=E.TASK_SUCCESS)
    artifact_id = insert_artifact(ds_id, task_id, name="任务1")
    return {"ds": ds_id, "batch": batch_id, "task": task_id, "artifact": artifact_id}


def assert_envelope(payload: dict[str, Any], expected_code: int = 0) -> Any:
    """统一响应信封：字段固定、成功 message 为 ok、失败 data 为 null。"""
    assert set(payload) == {"code", "data", "message"}, payload
    assert payload["code"] == expected_code
    if expected_code == 0:
        assert payload["message"] == "ok"
    else:
        assert payload["data"] is None
        assert isinstance(payload["message"], str) and payload["message"], "失败必须带人话"
    return payload["data"]


def assert_pagination(data: dict[str, Any], *, page: int, page_size: int) -> None:
    """分页负载固定 {items,total,page,pageSize}。"""
    assert set(data) == {"items", "total", "page", "pageSize"}, data
    assert data["page"] == page
    assert data["pageSize"] == page_size
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int) and data["total"] >= 0
    assert len(data["items"]) <= page_size


def walk_keys(value: Any, prefix: str = "") -> Iterator[str]:
    """递归遍历 JSON 的所有键名。"""
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child, prefix)


def collect_iso_values(value: Any) -> Iterator[str]:
    """递归收集所有形似 *_at 的字符串值。"""
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("_at") and isinstance(child, str):
                yield child
            else:
                yield from collect_iso_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from collect_iso_values(child)


# ---------------------------------------------------------------------------
# 信封契约（21 个 GET 端点）
# ---------------------------------------------------------------------------
GET_ENDPOINTS = [
    "/api/health",
    "/api/system/info",
    "/api/system/metrics",
    "/api/settings",
    "/api/dashboard/overview",
    "/api/dashboard/trend?granularity=day",
    "/api/dashboard/trend?granularity=week",
    "/api/dashboard/trend?granularity=month",
    "/api/dashboard/health?order=asc",
    "/api/data-sources",
    "/api/data-sources/{ds}",
    "/api/data-sources/{ds}/health",
    "/api/batches",
    "/api/batches/{batch}",
    "/api/batches/{batch}/progress",
    "/api/batches/{batch}/logs",
    "/api/batches/latest?data_source_id={ds}",
    "/api/tasks?batch_id={batch}",
    "/api/tasks/{task}",
    "/api/tasks/{task}/logs",
    "/api/artifacts",
    "/api/artifacts/{artifact}",
]


class TestEnvelope:
    """所有成功响应必须是 ``{code:0,data:...,message:"ok"}``。"""

    @pytest.mark.parametrize("path", GET_ENDPOINTS)
    def test_get_endpoint_envelope(
        self, client: TestClient, seeded: dict[str, int], path: str
    ) -> None:
        """GET 类端点的信封与业务码。"""
        url = path.format(**seeded)
        response = client.get(url)
        assert response.status_code == 200, f"{url} → {response.status_code}"
        assert_envelope(response.json(), 0)

    def test_create_batch_envelope(self, client: TestClient, site: Any) -> None:
        """POST /api/batches 返回 {batch_id, status:pending}。"""
        ds_id = support.create_source(client, site, name="建批次源")
        data = support.unwrap(
            client.post(
                "/api/batches",
                json={"data_source_id": ds_id, "strategy": "count", "strategy_params": {"n": 1}},
            )
        )
        assert set(data) == {"batch_id", "status"}
        assert isinstance(data["batch_id"], int) and data["batch_id"] > 0
        assert data["status"] in (E.BATCH_PENDING, E.BATCH_RUNNING)

    def test_settings_put_returns_full_payload(self, client: TestClient) -> None:
        """PUT /api/settings 返回全量设置，且线程上限立即同步到引擎。"""
        data = support.unwrap(client.put("/api/settings", json={"max_threads": 3}))
        assert data["max_threads"] == 3
        metrics = support.unwrap(client.get("/api/system/metrics"))
        assert metrics["threads"]["max"] == 3, "线程上限变更必须立即同步到引擎"

    def test_test_path_endpoint(self, client: TestClient, tmp_path: Any) -> None:
        """POST /api/settings/test-path 返回 {writable,errno,reason}。"""
        data = support.unwrap(
            client.post("/api/settings/test-path", json={"path": str(tmp_path / "可写目录")})
        )
        assert set(data) == {"writable", "errno", "reason"}
        assert data["writable"] is True

    def test_purge_logs_and_rebuild_stats(self, client: TestClient) -> None:
        """危险操作两个端点可用。"""
        assert support.unwrap(client.post("/api/settings/purge-logs", json={"keep_days": 7}))[
            "deleted"
        ] >= 0
        assert support.unwrap(client.post("/api/settings/rebuild-stats"))["updated"] >= 0


# ---------------------------------------------------------------------------
# 分页契约
# ---------------------------------------------------------------------------
class TestPagination:
    """分页负载结构与 pageSize 边界。"""

    @pytest.mark.parametrize(
        "path", ["/api/data-sources", "/api/batches", "/api/tasks", "/api/artifacts"]
    )
    def test_default_pagination_shape(self, client: TestClient, path: str) -> None:
        """默认 page=1 / pageSize=10。"""
        assert_pagination(support.unwrap(client.get(path)), page=1, page_size=10)

    def test_page_size_switch_and_page_echo(self, client: TestClient, site: Any) -> None:
        """切换 pageSize=2 后回显 pageSize=2，且 items 不超过 2 条。"""
        for index in range(3):
            support.create_source(client, site, name=f"分页源{index}")
        data = support.unwrap(client.get("/api/data-sources", params={"page": 2, "pageSize": 2}))
        assert_pagination(data, page=2, page_size=2)
        assert data["total"] == 3
        assert len(data["items"]) == 1, "第 2 页应只剩 1 条"

    @pytest.mark.parametrize(
        ("params", "label"),
        [
            ({"pageSize": 0}, "pageSize=0"),
            ({"pageSize": -5}, "pageSize 负数"),
            ({"pageSize": 500}, "pageSize 超大（>200）"),
            ({"page": 0}, "page=0"),
            ({"page": -1}, "page 负数"),
        ],
    )
    def test_invalid_pagination_rejected_with_1001(
        self, client: TestClient, params: dict[str, int], label: str
    ) -> None:
        """分页参数越界 → HTTP 400 + 1001。"""
        response = client.get("/api/artifacts", params=params)
        assert response.status_code == 400, label
        assert_envelope(response.json(), int(ErrCode.PARAM_INVALID))

    def test_page_size_upper_bound_accepted(self, client: TestClient) -> None:
        """pageSize=200 是允许的上界。"""
        data = support.unwrap(client.get("/api/artifacts", params={"pageSize": 200}))
        assert data["pageSize"] == 200


# ---------------------------------------------------------------------------
# 错误码分段
# ---------------------------------------------------------------------------
class TestErrorCodes:
    """错误码分段正确：1xxx 入参 / 2xxx 数据源 / 3xxx 调度 / 4xxx 解析下载 / 5xxx 系统。"""

    def test_1001_param_invalid(self, client: TestClient) -> None:
        """非法入参 → 1001。"""
        response = client.post(
            "/api/batches",
            json={"data_source_id": 1, "strategy": "count", "strategy_params": {"n": 0}},
        )
        assert response.status_code == 400
        assert_envelope(response.json(), int(ErrCode.PARAM_INVALID))

    def test_2001_data_source_not_found(self, client: TestClient) -> None:
        """数据源不存在 → 2001。"""
        response = client.get("/api/data-sources/999999")
        assert response.status_code == 404
        assert_envelope(response.json(), int(ErrCode.DS_NOT_FOUND))

    def test_2002_data_source_duplicate(self, client: TestClient, site: Any) -> None:
        """同 name + homepage_url 重复 → 2002。"""
        support.create_source(client, site, name="重复源")
        response = client.post(
            "/api/data-sources",
            json={
                "name": "重复源",
                "type": E.TYPE_TEXT,
                "homepage_url": site.url("text/list.html"),
            },
        )
        assert response.status_code == 409
        assert_envelope(response.json(), int(ErrCode.DS_DUPLICATE))

    def test_3003_ffmpeg_missing(
        self, client: TestClient, site: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """视频批次前置校验：ffmpeg 缺失 → 3003。"""
        from app.services import batch_service

        class _Missing:
            available = False
            version = None
            path = None

        monkeypatch.setattr(batch_service, "get_ffmpeg", lambda: _Missing())
        ds_id = support.create_source(client, site, name="视频源", kind=E.TYPE_VIDEO)
        response = client.post(
            "/api/batches",
            json={"data_source_id": ds_id, "strategy": "count", "strategy_params": {"n": 1}},
        )
        assert response.status_code == 400
        assert_envelope(response.json(), int(ErrCode.FFMPEG_MISSING))

    def test_3004_batch_not_found(self, client: TestClient) -> None:
        """批次不存在 → 3004。"""
        response = client.get("/api/batches/999999")
        assert response.status_code == 404
        assert_envelope(response.json(), int(ErrCode.BATCH_NOT_FOUND))

    def test_3006_nothing_to_retry(self, client: TestClient, seeded: dict[str, int]) -> None:
        """无可重试任务 → 3006。"""
        response = client.post(f"/api/batches/{seeded['batch']}/retry-failed")
        assert response.status_code == 409
        assert_envelope(response.json(), int(ErrCode.NOTHING_TO_RETRY))

    def test_3007_task_not_retryable(self, client: TestClient, seeded: dict[str, int]) -> None:
        """success 任务不可重试 → 3007。"""
        response = client.post(f"/api/tasks/{seeded['task']}/retry")
        assert response.status_code == 409
        assert_envelope(response.json(), int(ErrCode.TASK_NOT_RETRYABLE))

    def test_4003_task_not_found(self, client: TestClient) -> None:
        """任务不存在 → 4003。"""
        response = client.get("/api/tasks/999999")
        assert response.status_code == 404
        assert_envelope(response.json(), int(ErrCode.TASK_NOT_FOUND))

    def test_4004_artifact_not_found(self, client: TestClient) -> None:
        """产物不存在 → 4004。"""
        response = client.get("/api/artifacts/999999")
        assert response.status_code == 404
        assert_envelope(response.json(), int(ErrCode.ARTIFACT_NOT_FOUND))

    def test_4004_open_dir_when_file_missing(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """产物文件已缺失时「打开目录」→ 4004（而不是 500）。"""
        response = client.post(f"/api/artifacts/{seeded['artifact']}/open-dir")
        assert response.status_code == 404
        assert_envelope(response.json(), int(ErrCode.ARTIFACT_NOT_FOUND))

    def test_5002_path_not_writable(self, client: TestClient, tmp_path: Any) -> None:
        """输出根目录不可写（指向一个已存在的文件）→ 5002。"""
        blocker = tmp_path / "blocker.txt"
        blocker.write_text("x", encoding="utf-8")
        response = client.put("/api/settings", json={"output_root": str(blocker)})
        assert response.status_code == 500
        assert_envelope(response.json(), int(ErrCode.PATH_NOT_WRITABLE))

    def test_error_code_segments_are_in_documented_ranges(self) -> None:
        """错误码分段与架构 §4.7 一致（1000-5099 分段映射）。"""
        groups = {
            1000: (ErrCode.PARAM_INVALID, ErrCode.FILE_FORMAT, ErrCode.FILE_TOO_LARGE),
            2000: (ErrCode.DS_NOT_FOUND, ErrCode.DS_DUPLICATE, ErrCode.DS_BUSY),
            3000: (
                ErrCode.BATCH_SINGLE_FLIGHT,
                ErrCode.QUEUE_FULL,
                ErrCode.FFMPEG_MISSING,
                ErrCode.BATCH_NOT_FOUND,
                ErrCode.BATCH_STATE_INVALID,
                ErrCode.NOTHING_TO_RETRY,
                ErrCode.TASK_NOT_RETRYABLE,
                ErrCode.PAGE_OUT_OF_RANGE,
            ),
            4000: (
                ErrCode.SCRIPT_ERROR,
                ErrCode.SCRIPT_TIMEOUT,
                ErrCode.TASK_NOT_FOUND,
                ErrCode.ARTIFACT_NOT_FOUND,
                ErrCode.HTTP_ERROR,
                ErrCode.M3U8_PARSE,
                ErrCode.DRM_UNSUPPORTED,
                ErrCode.DISK_FULL,
            ),
            5000: (ErrCode.INTERNAL, ErrCode.OS_ACTION_FAILED, ErrCode.PATH_NOT_WRITABLE),
        }
        for base, codes in groups.items():
            for code in codes:
                assert base <= int(code) <= base + 99, f"{code} 超出 {base} 段"


# ---------------------------------------------------------------------------
# 字段契约：snake_case + ISO8601
# ---------------------------------------------------------------------------
class TestFieldContracts:
    """JSON 出参统一 snake_case（仅分页键 pageSize 例外），时间为 ISO8601 带时区。"""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/data-sources",
            "/api/batches",
            "/api/tasks",
            "/api/artifacts",
            "/api/settings",
            "/api/system/info",
            "/api/dashboard/overview",
        ],
    )
    def test_no_camel_case_keys(self, client: TestClient, path: str) -> None:
        """键名不得为驼峰（``pageSize`` 是唯一约定例外）。"""
        data = support.unwrap(client.get(path))
        offenders = {
            key
            for key in walk_keys(data)
            if key != "pageSize" and CAMEL_RE.match(key) and any(ch.isupper() for ch in key)
        }
        assert not offenders, f"{path} 出现驼峰字段：{offenders}"

    def test_iso8601_with_timezone(self, client: TestClient, seeded: dict[str, int]) -> None:
        """时间字段形如 ``2026-10-25T10:32:31.123+08:00``。"""
        payloads = [
            support.batch_detail(client, seeded["batch"]),
            support.source_detail(client, seeded["ds"]),
        ]
        values = [value for payload in payloads for value in collect_iso_values(payload)]
        assert values, "示例数据应至少包含一个时间字段"
        for value in values:
            assert ISO_RE.match(value), f"时间格式不符 ISO8601 毫秒+时区：{value}"

    def test_batch_detail_field_set(self, client: TestClient, seeded: dict[str, int]) -> None:
        """批次详情必须包含策略参数、游标前后与计数（§4.3 契约）。"""
        detail = support.batch_detail(client, seeded["batch"])
        required = {
            "id",
            "data_source_id",
            "strategy",
            "strategy_params",
            "status",
            "phase",
            "total_tasks",
            "done_tasks",
            "failed_tasks",
            "skipped_tasks",
            "progress",
            "cursor_before",
            "cursor_after",
            "warnings",
        }
        assert required <= set(detail), f"缺少字段：{required - set(detail)}"

    def test_task_item_field_set(self, client: TestClient, seeded: dict[str, int]) -> None:
        """任务列表项含 step 进度与 extra 摘要。"""
        task = support.tasks_of(client, seeded["batch"])[0]
        required = {
            "id",
            "batch_id",
            "data_source_id",
            "seq_no",
            "title",
            "source_url",
            "status",
            "attempt_count",
            "step_done",
            "step_total",
            "duration_ms",
            "extra",
        }
        assert required <= set(task), f"缺少字段：{required - set(task)}"


# ---------------------------------------------------------------------------
# OpenAPI 契约（NFR-13：前端 API 层与文档一一对应）
# ---------------------------------------------------------------------------
class TestOpenApi:
    """OpenAPI 文档可访问且端点数量与架构 §4 清单一致（43 个）。"""

    def test_docs_and_openapi_reachable(self, client: TestClient) -> None:
        """/docs 与 /openapi.json 均可访问。"""
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200

    def test_endpoint_catalog_matches_architecture(self, client: TestClient) -> None:
        """GET 22 / POST 16 / PUT 2 / DELETE 2 / PATCH 1，合计 43 个操作。"""
        spec = client.get("/openapi.json").json()
        operations = [
            (method.upper(), path) for path, item in spec["paths"].items() for method in item
        ]
        counts: dict[str, int] = {}
        for method, _path in operations:
            counts[method] = counts.get(method, 0) + 1
        assert len(operations) == 43, f"端点总数应为 43，实际 {len(operations)}：{sorted(counts.items())}"
        assert counts == {"GET": 22, "POST": 16, "PUT": 2, "DELETE": 2, "PATCH": 1}

    def test_all_api_paths_are_prefixed(self, client: TestClient) -> None:
        """所有业务路径均以 /api 前缀暴露（§11.1）。"""
        spec = client.get("/openapi.json").json()
        offenders = [path for path in spec["paths"] if not path.startswith("/api")]
        assert not offenders, f"存在未加 /api 前缀的路径：{offenders}"
class TestDataSourceApi:
    """数据源端点：CRUD、启停、脚本校验与试运行、导入导出。"""

    def test_create_update_toggle_delete_flow(self, client: TestClient, site: Any) -> None:
        """新增 → 编辑 → 停用 → 删除 全链路。"""
        ds_id = support.create_source(client, site, name="CRUD源")
        assert support.source_detail(client, ds_id)["name"] == "CRUD源"

        support.unwrap(client.put(f"/api/data-sources/{ds_id}", json={"category": "新分类"}))
        assert support.source_detail(client, ds_id)["category"] == "新分类"

        assert support.unwrap(
            client.patch(f"/api/data-sources/{ds_id}/enabled", json={"enabled": False})
        )["enabled"] is False
        listed = support.unwrap(client.get("/api/data-sources", params={"enabled": "false"}))
        assert [item["id"] for item in listed["items"]] == [ds_id]

        assert support.unwrap(client.delete(f"/api/data-sources/{ds_id}"))["deleted"] == 1
        assert client.get(f"/api/data-sources/{ds_id}").status_code == 404

    def test_keyword_search_hits_name_or_url(self, client: TestClient, site: Any) -> None:
        """关键字命中名称或地址。"""
        support.create_source(client, site, name="科幻小说站")
        support.create_source(client, site, name="新闻站")
        by_name = support.unwrap(client.get("/api/data-sources", params={"keyword": "科幻"}))
        assert [item["name"] for item in by_name["items"]] == ["科幻小说站"]
        by_url = support.unwrap(client.get("/api/data-sources", params={"keyword": "list.html"}))
        assert by_url["total"] == 2

    def test_type_filter_only_returns_that_type(self, client: TestClient, site: Any) -> None:
        """type 过滤只返回对应类型（PRD P0-06①）。"""
        support.create_source(client, site, name="文字源", kind=E.TYPE_TEXT)
        support.create_source(client, site, name="图片源", kind=E.TYPE_IMAGE)
        data = support.unwrap(client.get("/api/data-sources", params={"type": "image"}))
        assert [item["type"] for item in data["items"]] == ["image"]

    def test_script_validate_detects_syntax_error(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """语法错误返回 valid=false + 行号。"""
        data = support.unwrap(
            client.post(
                f"/api/data-sources/{seeded['ds']}/script/validate",
                json={"script": SCRIPT_SYNTAX_ERROR, "entry": "parse"},
            )
        )
        assert data["valid"] is False
        assert data["line"] == 1
        assert "语法" in data["message"]

    def test_script_validate_accepts_valid_script(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """合法脚本 valid=true。"""
        data = support.unwrap(
            client.post(
                f"/api/data-sources/{seeded['ds']}/script/validate",
                json={"script": SCRIPT_OK, "entry": "parse"},
            )
        )
        assert data["valid"] is True
        assert data["line"] is None

    def test_script_test_returns_first_five_samples(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """试运行返回条数、字段名与样例（≤5 条）。"""
        data = support.unwrap(
            client.post(
                f"/api/data-sources/{seeded['ds']}/script/test",
                json={"script": SCRIPT_OK, "entry": "parse", "url": "http://a.test/list"},
            )
        )
        assert data["count"] == 3
        assert set(data["fields"]) == {"title", "url"}
        assert len(data["samples"]) == 3

    def test_import_json_and_skip_duplicates(self, client: TestClient, site: Any) -> None:
        """导入 JSON：首次成功，重复行 skipped（overwrite=false）。"""
        rows = [
            {
                "name": "导入源",
                "type": "text",
                "category": "导入",
                "homepage_url": site.url("text/list.html"),
                "enabled": True,
            }
        ]
        content = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        first = support.unwrap(
            client.post(
                "/api/data-sources/import",
                files={"file": ("ds.json", content, "application/json")},
                data={"overwrite": "false"},
            )
        )
        assert first["success"] == 1 and first["failed"] == 0

        second = support.unwrap(
            client.post(
                "/api/data-sources/import",
                files={"file": ("ds.json", content, "application/json")},
                data={"overwrite": "false"},
            )
        )
        assert second["success"] == 0
        assert second["rows"][0]["status"] == "skipped"

    def test_import_reports_row_errors(self, client: TestClient) -> None:
        """字段缺失的行被跳过并给出逐行原因。"""
        rows = [{"name": "缺类型", "homepage_url": "http://a.test/x"}]
        content = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        data = support.unwrap(
            client.post(
                "/api/data-sources/import",
                files={"file": ("bad.json", content, "application/json")},
            )
        )
        assert data["success"] == 0
        assert data["failed"] == 1
        assert data["rows"][0]["reason"]

    def test_export_is_utf8_json_array(self, client: TestClient, seeded: dict[str, int]) -> None:
        """导出为 UTF-8 JSON 数组且字段与导入兼容。"""
        response = client.get("/api/data-sources/export", params={"scope": "all"})
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        rows = json.loads(response.content.decode("utf-8"))
        assert isinstance(rows, list) and rows
        assert {"name", "type", "homepage_url", "config_json"} <= set(rows[0])

    def test_export_scope_type_validates_argument(self, client: TestClient) -> None:
        """scope=type 但未给 type → 1001。"""
        response = client.get("/api/data-sources/export", params={"scope": "type"})
        assert response.status_code == 400
        assert_envelope(response.json(), int(ErrCode.PARAM_INVALID))

    def test_import_csv_with_pipe_separated_alt_urls(self, client: TestClient, site: Any) -> None:
        """CSV 导入：同名字段表头，alt_urls 用竖线分隔（A-08）。"""
        header = "name,type,category,homepage_url,alt_urls,enabled,is_novel\n"
        row = (
            f"CSV导入源,text,CSV分类,{site.url('text/list.html')},"
            f"{site.url('text/list.html')}|https://alt.test/x,1,0\n"
        )
        content = (header + row).encode("utf-8")
        data = support.unwrap(
            client.post(
                "/api/data-sources/import",
                files={"file": ("ds.csv", content, "text/csv")},
            )
        )
        assert data["success"] == 1, data
        listed = support.unwrap(client.get("/api/data-sources", params={"keyword": "CSV导入源"}))
        assert listed["total"] == 1
        assert listed["items"][0]["alt_urls_count"] == 2
        assert listed["items"][0]["type"] == "text"

    def test_export_then_reimport_is_lossless(
        self, client: TestClient, site: Any
    ) -> None:
        """导出 → 删除 → 重新导入：关键字段往返一致（P0-23②）。"""
        ds_id = support.create_source(client, site, name="往返源", category="往返分类")
        before = support.source_detail(client, ds_id)
        rows = json.loads(
            client.get("/api/data-sources/export", params={"scope": "all"}).content.decode("utf-8")
        )
        assert len(rows) == 1

        assert support.unwrap(client.delete(f"/api/data-sources/{ds_id}"))["deleted"] == 1
        imported = support.unwrap(
            client.post(
                "/api/data-sources/import",
                files={
                    "file": (
                        "roundtrip.json",
                        json.dumps(rows, ensure_ascii=False).encode("utf-8"),
                        "application/json",
                    )
                },
            )
        )
        assert imported["success"] == 1, imported

        listed = support.unwrap(client.get("/api/data-sources", params={"keyword": "往返源"}))
        after = support.source_detail(client, listed["items"][0]["id"])
        for field in (
            "name",
            "type",
            "category",
            "homepage_url",
            "config_json",
            "is_novel",
            "enabled",
            "script_entry",
        ):
            assert after[field] == before[field], f"字段 {field} 往返不一致"

    def test_template_download(self, client: TestClient) -> None:
        """导入模板为 JSON 附件且含示例字段。"""
        response = client.get("/api/data-sources/template")
        assert response.status_code == 200
        assert "attachment" in response.headers.get("content-disposition", "")
        rows = json.loads(response.content.decode("utf-8"))
        assert isinstance(rows, list) and rows
        assert {"name", "type", "homepage_url"} <= set(rows[0])


# ---------------------------------------------------------------------------
# 批次控制 / 日志
# ---------------------------------------------------------------------------
class TestBatchApi:
    """批次端点：暂停/恢复、日志过滤、进度字段。"""

    def test_pause_and_resume_pending_batch(self, client: TestClient, seeded: dict[str, int]) -> None:
        """pending 批次暂停 → paused，恢复 → running。"""
        batch_id = insert_batch(seeded["ds"], status=E.BATCH_PENDING, phase=E.PHASE_PARSE)
        assert support.unwrap(client.post(f"/api/batches/{batch_id}/pause"))["status"] == "paused"
        resumed = support.unwrap(client.post(f"/api/batches/{batch_id}/resume"))
        assert resumed["status"] == "running"
        support.wait_batch(client, batch_id)

    def test_progress_payload_shape(self, client: TestClient, seeded: dict[str, int]) -> None:
        """进度负载含 batch 卡与 active 列表。"""
        data = support.unwrap(client.get(f"/api/batches/{seeded['batch']}/progress"))
        assert set(data) >= {"batch", "active", "last_log_id"}
        assert set(data["batch"]) >= {
            "status",
            "phase",
            "progress",
            "total",
            "done",
            "failed",
            "skipped",
            "elapsed_ms",
        }
        assert isinstance(data["active"], list)

    def test_progress_with_after_log_id_returns_incremental_logs(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """携带 after_log_id 时返回增量日志数组。"""
        data = support.unwrap(
            client.get(
                f"/api/batches/{seeded['batch']}/progress", params={"after_log_id": 0}
            )
        )
        assert isinstance(data["logs"], list)

    def test_logs_level_filter(self, client: TestClient, seeded: dict[str, int]) -> None:
        """日志支持 level 过滤。"""
        from app.db.base import session_scope
        from app.db.models import TaskLog

        with session_scope() as db:
            db.add(
                TaskLog(
                    batch_id=seeded["batch"],
                    task_id=None,
                    level=E.LOG_WARN,
                    message="契约测试 WARN",
                )
            )
        warn = support.unwrap(
            client.get(f"/api/batches/{seeded['batch']}/logs", params={"level": "WARN"})
        )
        assert warn["items"] and all(item["level"] == "WARN" for item in warn["items"])
        keyword = support.unwrap(
            client.get(f"/api/batches/{seeded['batch']}/logs", params={"keyword": "契约测试"})
        )
        assert len(keyword["items"]) == 1

    def test_latest_returns_no_history_for_new_source(
        self, client: TestClient, site: Any
    ) -> None:
        """从未采集的数据源：has_history=false（PRD P0-07③）。"""
        ds_id = support.create_source(client, site, name="无历史源")
        data = support.unwrap(client.get("/api/batches/latest", params={"data_source_id": ds_id}))
        assert data["has_history"] is False

    def test_latest_returns_cursor_after_batch(
        self, client: TestClient, seeded: dict[str, int]
    ) -> None:
        """有历史批次时返回游标与最近状态。"""
        data = support.unwrap(
            client.get("/api/batches/latest", params={"data_source_id": seeded["ds"]})
        )
        assert data["has_history"] is True
        assert data["batch_id"] == seeded["batch"]


# ---------------------------------------------------------------------------
# 产物端点
# ---------------------------------------------------------------------------
class TestArtifactApi:
    """产物端点：5 条件组合筛选、文件存在性、删除。"""

    @pytest.fixture
    def artifacts(self, client: TestClient, site: Any, tmp_path: Any) -> dict[str, int]:
        """播种 3 条产物：成功文件 / 失败 / 图片目录。"""
        ds_id = support.create_source(client, site, name="产物源")
        batch_id = insert_batch(ds_id, status=E.BATCH_SUCCESS, total=3, done=2, failed=1)
        real_file = tmp_path / "存在.txt"
        real_file.write_text("x", encoding="utf-8")
        ids = {}
        for index, (status, art_type, name, path) in enumerate(
            [
                (E.ARTIFACT_SUCCESS, E.ARTIFACT_TEXT, "第一章", str(real_file)),
                (E.ARTIFACT_FAILED, E.ARTIFACT_PDF, "第二章", ""),
                (E.ARTIFACT_SUCCESS, E.ARTIFACT_IMAGE, "图集甲", str(tmp_path)),
            ],
            start=1,
        ):
            task_id = insert_task(batch_id, ds_id, status=E.TASK_SUCCESS, seq=index, title=name)
            ids[name] = insert_artifact(
                ds_id,
                task_id,
                status=status,
                art_type=art_type,
                name=name,
                path=path,
                size=16,
                error_msg="失败原因" if status == E.ARTIFACT_FAILED else None,
            )
        ids["ds"] = ds_id
        return ids

    def test_five_condition_filters(self, client: TestClient, artifacts: dict[str, int]) -> None:
        """数据源 / 类型 / 名称 / 状态 组合筛选生效。"""
        by_type = support.unwrap(client.get("/api/artifacts", params={"type": "image"}))
        assert by_type["total"] == 1
        by_status = support.unwrap(client.get("/api/artifacts", params={"status": "failed"}))
        assert by_status["total"] == 1
        by_name = support.unwrap(client.get("/api/artifacts", params={"name": "第"}))
        assert by_name["total"] == 2
        combined = support.unwrap(
            client.get(
                "/api/artifacts",
                params={"data_source_id": artifacts["ds"], "type": "text", "name": "第一"},
            )
        )
        assert combined["total"] == 1
        assert combined["items"][0]["name"] == "第一章"

    def test_is_file_exists_flag(self, client: TestClient, artifacts: dict[str, int]) -> None:
        """is_file_exists 正确区分真实文件 / 空路径。"""
        data = support.unwrap(client.get("/api/artifacts", params={"pageSize": 100}))
        flags = {item["name"]: item["is_file_exists"] for item in data["items"]}
        assert flags["第一章"] is True
        assert flags["第二章"] is False

    def test_artifact_detail_contains_error_msg(
        self, client: TestClient, artifacts: dict[str, int]
    ) -> None:
        """失败产物详情带 error_msg（PRD P1-05③）。"""
        detail = support.unwrap(client.get(f"/api/artifacts/{artifacts['第二章']}"))
        assert detail["status"] == E.ARTIFACT_FAILED
        assert detail["error_msg"]

    def test_redownload_only_for_failed_task(
        self, client: TestClient, artifacts: dict[str, int]
    ) -> None:
        """成功任务对应的产物不可「重新下载」→ 3007。"""
        response = client.post(f"/api/artifacts/{artifacts['第一章']}/redownload")
        assert response.status_code == 409
        assert_envelope(response.json(), int(ErrCode.TASK_NOT_RETRYABLE))

    def test_delete_artifact_record(self, client: TestClient, artifacts: dict[str, int]) -> None:
        """删除产物记录成功并可选择同时删文件。"""
        artifact_id = artifacts["第一章"]
        assert support.unwrap(
            client.delete(f"/api/artifacts/{artifact_id}", params={"delete_file": "false"})
        )["deleted"] == 1
        assert client.get(f"/api/artifacts/{artifact_id}").status_code == 404
