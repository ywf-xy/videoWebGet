"""pytest 公共装置：临时 SQLite / TestClient / 离线模拟站点 / 状态清理。

设计要点：
1. **环境隔离**：``CRAWLERHUB_DB`` / ``CRAWLERHUB_OUTPUT`` / ``CRAWLERHUB_LOG_DIR``
   必须在 ``app.config`` 导入前设置（config 在 import 时读取环境变量），因此本文件顶部
   先建临时目录再导入应用模块；
2. **完全离线**：所有抓取都指向本地 ``ThreadingHTTPServer``（模拟站点），不访问外网；
3. **用例独立**：每个用例前等待引擎空闲 + 清空全部业务表 + 清空产物目录 + 复位模拟站点。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# ---------------------------------------------------------------------------
# 1) 环境变量（必须先于 app.* 导入）
# ---------------------------------------------------------------------------
TMP_ROOT = Path(tempfile.mkdtemp(prefix="crawlerhub-tests-"))
DB_PATH = TMP_ROOT / "data" / "test.db"
OUTPUT_ROOT = TMP_ROOT / "output"
LOG_DIR = TMP_ROOT / "logs"

for _directory in (DB_PATH.parent, OUTPUT_ROOT, LOG_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

os.environ["CRAWLERHUB_DB"] = str(DB_PATH)
os.environ["CRAWLERHUB_OUTPUT"] = str(OUTPUT_ROOT)
os.environ["CRAWLERHUB_LOG_DIR"] = str(LOG_DIR)
os.environ["CRAWLERHUB_HOST"] = "127.0.0.1"
os.environ["CRAWLERHUB_PORT"] = "18000"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import E  # noqa: E402

# ---------------------------------------------------------------------------
# 2) 模拟站点
# ---------------------------------------------------------------------------
_DETAIL_RE = re.compile(r"^/(video|text|image)/\d+\.html$")

_JPEG = (
    bytes.fromhex("ffd8ffe000104a46494600010100000100010000")
    + b"\x00" * 512
    + bytes.fromhex("ffd9")
)


class MockSite:
    """可编程离线站点：列表页 / 详情页 / m3u8 / 图片 + 并发与失败注入。

    并发统计口径：
    - ``max_detail_inflight``：同时处理「条目详情页」请求的峰值（≈ 任务级并发）；
    - ``max_total_inflight``：全部请求的并发峰值（含分片/图片，供观察参考）。
    """

    def __init__(self) -> None:
        self.base_url = ""
        self.page_size = 2
        self.delay = 0.0
        self.image_delay = 0.0
        self.status_overrides: dict[str, int] = {}
        self.m3u8_mode = "plain"
        self.segment_count = 3
        self.key = bytes(range(16))
        self.iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        self.videos: list[dict[str, Any]] = []
        self.chapters: list[dict[str, Any]] = []
        self.galleries: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.total_inflight = 0
        self.max_total_inflight = 0
        self.detail_inflight = 0
        self.max_detail_inflight = 0
        self.hits: Counter[str] = Counter()
        self.seed_defaults()

    # -- 内容 ----------------------------------------------------------
    def seed_defaults(self) -> None:
        """默认内容：2 页视频 / 2 页章节 / 1 页图集。"""
        self.videos = [
            {"id": i, "title": f"测试视频{i}", "date": f"2026-10-{10 + i:02d}"}
            for i in range(1, 5)
        ]
        self.chapters = [
            {"id": i, "title": f"第{i:03d}章 章节{i}", "date": f"2026-10-{10 + i:02d}"}
            for i in range(1, 5)
        ]
        self.galleries = [
            {"id": 1, "title": "夏日写真", "date": "2026-10-20", "images": 3}
        ]

    def reset(self) -> None:
        """复位统计与注入项（每个用例前调用）。"""
        with self.lock:
            self.total_inflight = 0
            self.max_total_inflight = 0
            self.detail_inflight = 0
            self.max_detail_inflight = 0
            self.hits = Counter()
        self.delay = 0.0
        self.image_delay = 0.0
        self.status_overrides = {}
        self.m3u8_mode = "plain"
        self.segment_count = 3
        self.page_size = 2
        self.seed_defaults()

    def url(self, path: str) -> str:
        """把站点相对路径拼成绝对地址。"""
        return f"{self.base_url}/{path.lstrip('/')}"

    def delay_for(self, path: str, is_detail: bool) -> float:
        """按请求类型返回注入延迟（详情/图片可分别控制，便于稳定制造并发与暂停时机）。"""
        if is_detail:
            return self.delay
        if path.startswith("/img/"):
            return self.image_delay
        return min(self.delay, 0.02)

    # -- 请求处理 ------------------------------------------------------
    def serve(self, handler: BaseHTTPRequestHandler) -> None:
        """处理一次 GET 请求（含并发计数与延迟注入）。"""
        parsed = urlsplit(handler.path)
        path = parsed.path
        page = _safe_int((parse_qs(parsed.query).get("page") or ["1"])[0], 1)
        is_detail = bool(_DETAIL_RE.match(path))
        with self.lock:
            self.hits[path] += 1
            self.total_inflight += 1
            self.max_total_inflight = max(self.max_total_inflight, self.total_inflight)
            if is_detail:
                self.detail_inflight += 1
                self.max_detail_inflight = max(
                    self.max_detail_inflight, self.detail_inflight
                )
        try:
            pause_delay = self.delay_for(path, is_detail)
            if pause_delay:
                time.sleep(pause_delay)
            status, content_type, body = self.render(path, page)
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # 客户端提前断开
            pass
        finally:
            with self.lock:
                self.total_inflight -= 1
                if is_detail:
                    self.detail_inflight -= 1

    def render(self, path: str, page: int) -> tuple[int, str, bytes]:
        """按路径返回 (status, content_type, body)。"""
        override = self.status_overrides.get(path)
        if override is not None:
            return override, "text/plain; charset=utf-8", b"injected error"

        if path in ("/video/list.html", "/text/list.html", "/image/list.html"):
            return 200, "text/html; charset=utf-8", self._list_page(path, page)

        match = _DETAIL_RE.match(path)
        if match:
            kind = match.group(1)
            item_id = _safe_int(path.split("/")[-1].split(".")[0], 1)
            return 200, "text/html; charset=utf-8", self._detail_page(kind, item_id)

        match = re.match(r"^/media/(\d+)/index\.m3u8$", path)
        if match:
            return 200, "application/vnd.apple.mpegurl", self._playlist(int(match.group(1)))

        match = re.match(r"^/media/(\d+)/seg(\d+)\.ts$", path)
        if match:
            index = int(match.group(2))
            return 200, "video/mp2t", self._segment(int(match.group(1)), index)

        if path == "/media/key.bin":
            return 200, "application/octet-stream", self.key

        match = re.match(r"^/img/(\d+)/(\d+)\.jpg$", path)
        if match:
            return 200, "image/jpeg", _JPEG

        return 404, "text/plain; charset=utf-8", b"not found"

    # -- 页面渲染 ------------------------------------------------------
    def _list_page(self, path: str, page: int) -> bytes:
        """渲染列表页（每页 page_size 条）。"""
        if path.startswith("/video"):
            items = self.videos
        elif path.startswith("/text"):
            items = self.chapters
        else:
            items = self.galleries
        start = max(0, (page - 1) * self.page_size)
        chunk = items[start : start + self.page_size]
        rows = "".join(
            f'<li><a href="/{path.split("/")[1]}/{item["id"]}.html">{item["title"]}</a>'
            f'<span class="date">{item.get("date", "")}</span></li>'
            for item in chunk
        )
        return (
            "<!doctype html><html><body><ul class=\"list\">"
            f"{rows}</ul></body></html>"
        ).encode("utf-8")

    def _detail_page(self, kind: str, item_id: int) -> bytes:
        """渲染详情页（视频 / 章节 / 图集）。"""
        if kind == "video":
            return (
                "<!doctype html><html><body><h1>视频详情</h1>"
                f'<video src="/media/{item_id}/index.m3u8"></video>'
                "</body></html>"
            ).encode("utf-8")
        if kind == "text":
            return (
                "<!doctype html><html><body>"
                f"<h1>章节{item_id}</h1>"
                f'<div id="content">这是第 {item_id} 章的正文内容，'
                "用于验证中文落盘与 PDF 字体。中文不能出现方块。</div>"
                "</body></html>"
            ).encode("utf-8")
        gallery = next((item for item in self.galleries if item["id"] == item_id), None)
        count = int(gallery["images"]) if gallery else 3
        images = "".join(f'<img src="/img/{item_id}/{index}.jpg"/>' for index in range(1, count + 1))
        return (
            f"<!doctype html><html><body><h1>图集{item_id}</h1>"
            f'<div class="gallery">{images}</div>'
            "</body></html>"
        ).encode("utf-8")

    def _playlist(self, video_id: int) -> bytes:
        """渲染 m3u8（支持明文 / AES-128 / SAMPLE-AES 三种模式）。"""
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
        if self.m3u8_mode == "aes128":
            lines.insert(
                1,
                '#EXT-X-KEY:METHOD=AES-128,URI="/media/key.bin",'
                f"IV=0x{self.iv.hex()}",
            )
        elif self.m3u8_mode == "aes128_no_iv":
            lines.insert(1, '#EXT-X-KEY:METHOD=AES-128,URI="/media/key.bin"')
        elif self.m3u8_mode == "sample_aes":
            lines.insert(1, '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="/media/key.bin"')
        for index in range(self.segment_count):
            lines.append("#EXTINF:2.000,")
            lines.append(f"seg{index}.ts")
        lines.append("#EXT-X-ENDLIST")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def plain_segment(self, video_id: int, index: int) -> bytes:
        """明文分片内容（加密模式下为其密文）。"""
        return bytes([0x47]) + bytes([(video_id + index) % 256]) * 183

    def _segment(self, video_id: int, index: int) -> bytes:
        """返回分片内容（AES-128 模式下用密钥加密，便于验证下载器解密）。"""
        data = self.plain_segment(video_id, index)
        if self.m3u8_mode not in ("aes128", "aes128_no_iv"):
            return data
        from Crypto.Cipher import AES  # pycryptodome（requirements.txt 已声明）
        from Crypto.Util.Padding import pad

        iv = self.iv if self.m3u8_mode == "aes128" else int(index).to_bytes(16, "big")
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return cipher.encrypt(pad(data, 16))


def _safe_int(text: str, default: int) -> int:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def _make_handler(site: MockSite) -> type[BaseHTTPRequestHandler]:
    """生成绑定到指定站点的请求处理器。"""

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
            site.serve(self)

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 静默
            return

    return _Handler


# ---------------------------------------------------------------------------
# 3) 会话级 fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def site() -> Iterator[MockSite]:
    """启动本地模拟站点（进程内 ThreadingHTTPServer）。"""
    mock = MockSite()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(mock))
    mock.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, name="mock-site", daemon=True)
    thread.start()
    yield mock
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """FastAPI TestClient（进入时触发 lifespan：建库 + 启动引擎）。"""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 4) 用例级清理
# ---------------------------------------------------------------------------
def wait_engine_idle(timeout: float = 40.0, quiet_window: float = 0.3) -> None:
    """等待引擎静默（无执行体、无活跃任务）。

    说明：直接落库的 pending/running 批次可能没有对应执行体（用例播种状态），
    此时只需确认「无执行体 + 活跃计数为 0」并保持一个短暂的安静窗口，
    即可认为引擎已静默；有执行体的批次则请求暂停让其自然收尾。
    """
    from app.db.base import session_scope
    from app.db.models import CrawlBatch
    from app.engine.crawler_engine import get_engine
    from app.engine.pause_control import pause_controller

    engine = get_engine()
    deadline = time.time() + timeout
    quiet_since: float | None = None
    while time.time() < deadline:
        with session_scope() as db:
            ids = [
                int(row[0])
                for row in db.query(CrawlBatch.id)
                .filter(CrawlBatch.status.in_((E.BATCH_PENDING, E.BATCH_RUNNING)))
                .all()
            ]
        alive = [batch_id for batch_id in ids if engine.is_running(batch_id)]
        if not alive and engine.active_count() == 0:
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since >= quiet_window:
                return
        else:
            quiet_since = None
            for batch_id in ids:
                pause_controller.request(batch_id)
        time.sleep(0.05)


def wipe_business_tables() -> None:
    """清空全部业务表（保留表结构与 app_setting 的 schema 版本）。"""
    from sqlalchemy import delete

    from app.db.base import session_scope
    from app.db.models import (
        AppSetting,
        Artifact,
        CrawlBatch,
        CrawlTask,
        DataSource,
        TaskLog,
        TaskResult,
    )

    with session_scope() as db:
        for model in (TaskLog, TaskResult, Artifact, CrawlTask, CrawlBatch, DataSource):
            db.execute(delete(model))
        db.execute(delete(AppSetting).where(AppSetting.key != "_schema_version"))


def wipe_output_dir() -> None:
    """清空产物目录（用例间隔离落盘文件）。"""
    shutil.rmtree(OUTPUT_ROOT, ignore_errors=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def reset_pause_state() -> None:
    """清空 PauseController 的全局登记表。

    必要性：本套件每例清空业务表后，SQLite 的 rowid 会从 1 重新分配，
    批次 id 因此被复用；而 ``PauseController._events`` 只在 ``_finalize`` 中
    ``release``，暂停结束（paused）的批次会一直保留 **已清除** 的事件。
    ``register()`` 只在事件不存在时 ``set()``，于是 id 复用后新批次会被误判为
    「已暂停」，进而卡在 paused_with_warning。
    （该现象在真实运行中不会出现，因为批次记录不会被删除；已在 TEST-REPORT 记为
    「健壮性观察项」，建议 register() 无条件 set()。）
    """
    from app.engine.pause_control import pause_controller

    with pause_controller._lock:  # noqa: SLF001 - 测试装置需要完全复位共享状态
        pause_controller._events.clear()  # noqa: SLF001
        pause_controller._active.clear()  # noqa: SLF001


@pytest.fixture(autouse=True)
def clean_state(client: TestClient, site: MockSite) -> Iterator[None]:
    """每个用例前复位引擎 / 数据库 / 产物目录 / 模拟站点。"""
    from app.engine.crawler_engine import get_engine

    wait_engine_idle()
    reset_pause_state()
    wipe_business_tables()
    wipe_output_dir()
    site.reset()
    # 设置表被清空 → 并发上限回到默认值（避免上一个用例改的 max_threads 影响后续）
    get_engine().sync_limit()
    yield
    wait_engine_idle()
