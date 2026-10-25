"""离线自测脚本（不联网）：用本地 HTTP 服务模拟三类站点，跑通全链路。

覆盖：
1. 视频链路：静态列表页 → 详情页 → m3u8（3 个 ts 分片）→ 分片并发下载 → concat。
   ffmpeg 被判为不可用时，必须走「本地 concat → .ts」兜底路径，任务按 PRD 标 failed(3003)，
   但产物文件必须真实存在且大小 > 0。
2. 文字链路：章节页 → 正文抽取 → TXT 落盘（PDF 可选）。
3. 图片链路：图集列表页 → 图集详情 → 3 张图下载为 001.jpg/002.jpg/003.jpg。
4. AES-128-CBC 解密实现与 NIST 测试向量对齐（m3u8 加密分片依赖）。

运行：
    backend/.venv/Scripts/python.exe backend/scripts/selftest_offline.py

退出码 0 = 全部通过；非 0 = 有断言失败。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# 1) 环境隔离：必须在导入 app 之前设置（config 在 import 时读取环境变量）
# ---------------------------------------------------------------------------
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="crawlerhub-selftest-"))
SITE_DIR = TEMP_ROOT / "site"
DB_PATH = TEMP_ROOT / "data" / "selftest.db"
OUTPUT_DIR = TEMP_ROOT / "output"
LOG_DIR = TEMP_ROOT / "logs"

for directory in (SITE_DIR, DB_PATH.parent, OUTPUT_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

os.environ["CRAWLERHUB_DB"] = str(DB_PATH)
os.environ["CRAWLERHUB_OUTPUT"] = str(OUTPUT_DIR)
os.environ["CRAWLERHUB_LOG_DIR"] = str(LOG_DIR)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.common.logger import setup_logging  # noqa: E402
from app.common.path_builder import PathBuilder  # noqa: E402
from app.config import E  # noqa: E402
from app.db.base import init_db, session_scope  # noqa: E402
from app.db.models import Artifact, CrawlBatch, CrawlTask  # noqa: E402
from app.common.errors import BizError  # noqa: E402
from app.downloader.ffmpeg import FfmpegConverter  # noqa: E402
from app.downloader.m3u8_downloader import aes128_cbc_decrypt, _HAS_PYCRYPTODOME  # noqa: E402
from app.engine.crawler_engine import get_engine  # noqa: E402
from app.schemas.data_source import DataSourceCreate  # noqa: E402
from app.schemas.batch import BatchCreate  # noqa: E402
from app.services import batch_service, data_source_service  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str, extra: str = "") -> None:
    """断言并打印结果。"""
    if condition:
        print(f"  [PASS] {label}")
    else:
        FAILURES.append(f"{label} {extra}".strip())
        print(f"  [FAIL] {label} {extra}".strip())


# ---------------------------------------------------------------------------
# 2) 构造模拟站点
# ---------------------------------------------------------------------------
def build_site() -> None:
    """写入静态站点文件（列表页 / 详情页 / m3u8 / 分片 / 图片）。"""
    media = SITE_DIR / "media"
    images = SITE_DIR / "img"
    media.mkdir(parents=True, exist_ok=True)
    images.mkdir(parents=True, exist_ok=True)

    # --- 视频列表 + 详情 ---
    (SITE_DIR / "video_list.html").write_text(
        """<!doctype html><html><body><ul class="list">
<li><a href="/video_detail_1.html">测试视频一</a></li>
<li><a href="/video_detail_2.html">测试视频二</a></li>
</ul></body></html>""",
        encoding="utf-8",
    )
    for index in (1, 2):
        (SITE_DIR / f"video_detail_{index}.html").write_text(
            f"""<!doctype html><html><body>
<h1>测试视频{index}</h1>
<video src="/media/playlist.m3u8"></video>
</body></html>""",
            encoding="utf-8",
        )

    # --- m3u8（明文，3 个分片）---
    playlist = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
    for index in range(3):
        playlist.append("#EXTINF:2.000,")
        playlist.append(f"seg{index}.ts")
    playlist.append("#EXT-X-ENDLIST")
    (media / "playlist.m3u8").write_text("\n".join(playlist) + "\n", encoding="utf-8")

    # 分片内容：带 MPEG-TS 同步字节 0x47 的伪数据（仅验证下载/合并链路）
    for index in range(3):
        (media / f"seg{index}.ts").write_bytes(bytes([0x47]) + bytes([index]) * 2047)

    # --- 文字列表 + 章节 ---
    (SITE_DIR / "text_list.html").write_text(
        """<!doctype html><html><body><ul class="list">
<li><a href="/text_detail_1.html">第001章 科学边界</a></li>
<li><a href="/text_detail_2.html">第002章 台球</a></li>
</ul></body></html>""",
        encoding="utf-8",
    )
    for index, chapter in ((1, "第001章 科学边界"), (2, "第002章 台球")):
        (SITE_DIR / f"text_detail_{index}.html").write_text(
            f"""<!doctype html><html><body><h1>{chapter}</h1>
<div id="content">这是{chapter}的正文内容。<br/>中文排版需要正确的字体注册，否则 PDF 会出现方块。</div>
</body></html>""",
            encoding="utf-8",
        )

    # --- 图片列表 + 图集 ---
    (SITE_DIR / "image_list.html").write_text(
        """<!doctype html><html><body><ul class="list">
<li><a href="/image_detail_1.html">夏日写真</a></li>
</ul></body></html>""",
        encoding="utf-8",
    )
    (SITE_DIR / "image_detail_1.html").write_text(
        """<!doctype html><html><body><h1>夏日写真</h1>
<div class="gallery"><img src="/img/1.jpg"/><img src="/img/2.jpg"/><img src="/img/3.jpg"/></div>
</body></html>""",
        encoding="utf-8",
    )
    # 最小 JPEG 头部字节（仅验证落盘与命名，不做图片解码）
    jpeg = bytes.fromhex("ffd8ffe000104a46494600010100000100010000") + b"\x00" * 512 + bytes.fromhex("ffd9")
    for index in (1, 2, 3):
        (images / f"{index}.jpg").write_bytes(jpeg)


class QuietHandler(SimpleHTTPRequestHandler):
    """静默的静态文件处理器（避免污染自测输出）。"""

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        return


class _FakeFfmpegAvailable:
    """自测替身：仅让「创建视频批次」的前置校验通过。

    真实执行阶段仍使用全局 ffmpeg 封装（``force_unavailable=True``），
    从而覆盖 A-06 ② 的「中途缺失 → 降级 .ts」路径。
    """

    available = True
    version = "selftest-fake"
    path = "selftest-fake"


def patch_ffmpeg_available() -> None:
    """仅替换 batch_service 使用的 ffmpeg 探测结果。"""
    batch_service.get_ffmpeg = lambda: _FakeFfmpegAvailable()  # type: ignore[assignment]


def start_server() -> tuple[ThreadingHTTPServer, str]:
    """启动本地静态服务，返回 (server, base_url)。"""
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(SITE_DIR), **kwargs)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


# ---------------------------------------------------------------------------
# 3) 用例
# ---------------------------------------------------------------------------
def case_aes() -> None:
    """AES-128-CBC 解密对齐 NIST SP 800-38A 测试向量。"""
    print("\n[1/5] AES-128-CBC 解密实现校验")
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    cipher = bytes.fromhex("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2")
    plain = aes128_cbc_decrypt(cipher, key, iv)
    expected = bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")
    check(plain == expected, "NIST 向量解密结果一致", f"(got={plain.hex()})")
    print(f"  [INFO] 解密后端：{'pycryptodome' if _HAS_PYCRYPTODOME else '纯 Python AES'}")


def create_source(
    name: str,
    ds_type: str,
    list_file: str,
    config: dict,
    *,
    is_novel: bool = False,
) -> int:
    """创建自测数据源。"""
    with session_scope() as db:
        ds_id = data_source_service.create(
            db,
            DataSourceCreate(
                name=name,
                type=ds_type,
                category="自测",
                homepage_url=f"{BASE_URL}/{list_file}",
                config_json=config,
                is_novel=is_novel,
                enabled=True,
            ),
        )
    return ds_id


def run_batch(ds_id: int, strategy: str, params: dict, export_format: str | None = None) -> int:
    """创建批次并等待终态，返回 batch_id。"""
    with session_scope() as db:
        created = batch_service.create(
            db,
            BatchCreate(
                data_source_id=ds_id,
                strategy=strategy,
                strategy_params=params,
                export_format=export_format,
            ),
        )
    batch_id = created.batch_id
    deadline = time.time() + 120
    while time.time() < deadline:
        with session_scope() as db:
            batch = db.get(CrawlBatch, batch_id)
            status = str(batch.status) if batch else ""
        if status in E.BATCH_TERMINAL_STATUSES:
            break
        time.sleep(0.2)
    return batch_id


def batch_snapshot(batch_id: int) -> dict:
    """读取批次终态快照。"""
    with session_scope() as db:
        batch = db.get(CrawlBatch, batch_id)
        assert batch is not None
        tasks = [
            {
                "id": int(task.id),
                "status": str(task.status),
                "error_code": task.error_code,
                "step_done": int(task.step_done or 0),
                "step_total": int(task.step_total or 1),
                "title": str(task.title),
            }
            for task in db.query(CrawlTask).filter(CrawlTask.batch_id == batch_id).all()
        ]
        artifacts = [
            {
                "path": str(item.path),
                "size": int(item.size or 0),
                "status": str(item.status),
                "type": str(item.type),
            }
            for item in db.query(Artifact)
            .filter(Artifact.task_id.in_([task["id"] for task in tasks] or [0]))
            .all()
        ]
        return {
            "status": str(batch.status),
            "phase": str(batch.phase),
            "total": int(batch.total_tasks or 0),
            "done": int(batch.done_tasks or 0),
            "failed": int(batch.failed_tasks or 0),
            "skipped": int(batch.skipped_tasks or 0),
            "tasks": tasks,
            "artifacts": artifacts,
        }


def case_video() -> None:
    """视频链路：解析 → 建任务 → 分片下载 → 兜底 concat。"""
    print("\n[2/5] 视频链路（m3u8 → 分片 → 本地 concat 兜底）")
    ds_id = create_source(
        "自测影视站",
        E.TYPE_VIDEO,
        "video_list.html",
        {
            "list_url": f"{BASE_URL}/video_list.html",
            "item_selector": "li",
            "link_selector": "a@href",
            "title_selector": "a@text",
            "detail_video_selector": "video@src",
            "max_pages": 1,
        },
    )

    # A-06 ①：ffmpeg 缺失时创建视频批次应前置拦截（避免整批白跑）
    rejected = False
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
    except BizError as exc:
        rejected = exc.code == 3003
    check(rejected, "ffmpeg 缺失时创建视频批次被拒绝（3003 前置拦截）")

    # A-06 ②：假设已进入执行（并发中途卸载 ffmpeg），验证降级 concat 路径
    patch_ffmpeg_available()
    batch_id = run_batch(ds_id, E.STRATEGY_COUNT, {"n": 2})
    snapshot = batch_snapshot(batch_id)
    print(
        f"  [INFO] 批次 #{batch_id} 状态={snapshot['status']} 任务 {snapshot['total']} "
        f"成功 {snapshot['done']} 失败 {snapshot['failed']}"
    )
    check(snapshot["total"] == 2, "解析到 2 条视频并建 2 个任务", f"(实际 {snapshot['total']})")
    check(
        all(task["status"] == E.TASK_FAILED for task in snapshot["tasks"]),
        "ffmpeg 缺失时任务标记 failed（PRD P0-10④）",
    )
    check(
        all(str(task["error_code"]) == "3003" for task in snapshot["tasks"]),
        "失败原因错误码为 3003 FFMPEG_MISSING",
    )
    check(len(snapshot["artifacts"]) == 2, "每条任务都登记了产物", f"(实际 {len(snapshot['artifacts'])})")
    for artifact in snapshot["artifacts"]:
        path = Path(artifact["path"])
        check(
            path.suffix == ".ts" and path.exists() and path.stat().st_size > 0,
            f"兜底 .ts 产物落盘且非空：{path.name}",
            f"(size={path.stat().st_size if path.exists() else 0})",
        )
        check(artifact["status"] == E.ARTIFACT_FAILED, "产物状态为 failed（同时保留可播放文件）")


def case_text() -> None:
    """文字链路：章节正文 → TXT / PDF 落盘。"""
    print("\n[3/5] 文字链路（章节正文 → TXT + PDF）")
    ds_id = create_source(
        "自测小说网",
        E.TYPE_TEXT,
        "text_list.html",
        {
            "list_url": f"{BASE_URL}/text_list.html",
            "item_selector": "li",
            "link_selector": "a@href",
            "title_selector": "a@text",
            "detail_content_selector": "#content",
            "max_pages": 1,
        },
        is_novel=True,
    )
    batch_id = run_batch(ds_id, E.STRATEGY_COUNT, {"n": 2}, export_format="pdf")
    snapshot = batch_snapshot(batch_id)
    print(
        f"  [INFO] 批次 #{batch_id} 状态={snapshot['status']} 任务 {snapshot['total']} "
        f"成功 {snapshot['done']} 失败 {snapshot['failed']}"
    )
    check(snapshot["total"] == 2, "解析到 2 个章节", f"(实际 {snapshot['total']})")
    check(snapshot["done"] == 2, "2 个章节全部成功", f"(done={snapshot['done']})")
    for artifact in snapshot["artifacts"]:
        path = Path(artifact["path"])
        check(path.exists() and path.stat().st_size > 0, f"文字产物落盘且非空：{path.name}")
    pdf_count = sum(1 for item in snapshot["artifacts"] if Path(item["path"]).suffix == ".pdf")
    print(f"  [INFO] 其中 PDF 产物 {pdf_count} 个（PDF 失败会降级为 TXT）")


def case_image() -> None:
    """图片链路：图集 → 3 张图按序号落盘。"""
    print("\n[4/5] 图片链路（图集 → 001/002/003.jpg）")
    ds_id = create_source(
        "自测图库",
        E.TYPE_IMAGE,
        "image_list.html",
        {
            "list_url": f"{BASE_URL}/image_list.html",
            "item_selector": "li",
            "link_selector": "a@href",
            "title_selector": "a@text",
            "detail_image_selector": ".gallery img@src",
            "max_pages": 1,
        },
    )
    batch_id = run_batch(ds_id, E.STRATEGY_COUNT, {"n": 1})
    snapshot = batch_snapshot(batch_id)
    print(
        f"  [INFO] 批次 #{batch_id} 状态={snapshot['status']} 任务 {snapshot['total']} "
        f"成功 {snapshot['done']} 失败 {snapshot['failed']}"
    )
    check(snapshot["done"] == 1, "图集任务成功", f"(done={snapshot['done']})")
    check(len(snapshot["artifacts"]) == 1, "登记 1 个图片产物")
    if snapshot["artifacts"]:
        directory = Path(snapshot["artifacts"][0]["path"])
        files = sorted(item.name for item in directory.iterdir()) if directory.exists() else []
        check(directory.is_dir(), "图片产物为目录")
        check(
            files == ["001.jpg", "002.jpg", "003.jpg"],
            "图片按序号 001 起命名",
            f"(实际 {files})",
        )
        check(
            all((directory / name).stat().st_size > 0 for name in files) if files else False,
            "每张图片大小 > 0",
        )


def case_path_rules() -> None:
    """路径规则：四种模板与分类兜底。"""
    print("\n[5/5] 路径构建规则（PRD 9.1）")

    class FakeDs:
        """最小数据源替身。"""

        def __init__(self, name: str, category: str | None, is_novel: bool = False) -> None:
            self.name = name
            self.category = category
            self.is_novel = is_novel

    builder = PathBuilder(OUTPUT_DIR)
    video = builder.build_video(FakeDs("某某影视", "科幻"), "星际穿越")
    check(
        video.replace("\\", "/").endswith("某某影视/科幻/星际穿越.mp4"),
        "视频模板 {root}/{ds}/{category}/{name}.mp4",
        video,
    )
    novel = builder.build_text(
        FakeDs("某某小说网", "科幻", True), title="三体", chapter="第001章 科学边界", fmt="txt"
    )
    check(
        novel.replace("\\", "/").endswith("某某小说网/科幻/三体/第001章 科学边界.txt"),
        "小说模板 {root}/{ds}/{category}/{小说名}/{章节}.txt",
        novel,
    )
    article = builder.build_text(
        FakeDs("某新闻站", ""), title="AI 芯片发布", fmt="txt", when="2026-10-25"
    )
    check(
        article.replace("\\", "/").endswith("某新闻站/未分类/2026-10-25/AI 芯片发布.txt"),
        "非小说模板含日期且分类空 → 未分类",
        article,
    )
    image_dir = builder.build_image_dir(FakeDs("某图库", "写真"), "夏日", when="2026-10-25")
    check(
        image_dir.replace("\\", "/").endswith("某图库/写真/2026-10-25/夏日"),
        "图片模板 {root}/{ds}/{category}/{date}/{name}/",
        image_dir,
    )
    first = Path(builder.build_image_path(FakeDs("某图库", "写真"), "夏日", 1, 24, "jpg", when="2026-10-25"))
    check(first.name == "001.jpg", "图片序号位宽 ≥3 且从 001 起", first.name)


# ---------------------------------------------------------------------------
# 4) 入口
# ---------------------------------------------------------------------------
BASE_URL = ""


def main() -> int:
    """执行全部自测用例。"""
    global BASE_URL
    setup_logging(LOG_DIR)
    build_site()
    server, BASE_URL = start_server()
    print(f"模拟站点已启动：{BASE_URL}")
    print(f"隔离目录：{TEMP_ROOT}")

    # 强制 ffmpeg 不可用，验证兜底 concat 路径
    FfmpegConverter.force_unavailable = True

    init_db()
    engine = get_engine()
    engine.start()

    try:
        case_aes()
        case_video()
        case_text()
        case_image()
        case_path_rules()
    finally:
        engine.shutdown()
        server.shutdown()
        server.server_close()

    print("\n" + "=" * 64)
    if FAILURES:
        print(f"自测失败：{len(FAILURES)} 项")
        for item in FAILURES:
            print(f"  - {item}")
        print(f"产物目录（保留供排查）：{OUTPUT_DIR}")
        return 1
    print("自测全部通过：三条链路产物均已落盘且大小 > 0")
    shutil.rmtree(TEMP_ROOT, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
