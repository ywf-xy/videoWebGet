"""BUG-02 验收脚本（一次性，不入库）：8 线程并发建同源批次，只允许 1 个成功。

隔离方式：临时 DB + 把 engine.submit_batch 替换为 no-op（只测「创建期」竞态，
不让批次真的跑起来，从而放大并发窗口、结果可判定）。

用法：cd backend && .venv/Scripts/python.exe <本文件路径>
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TEMP = Path(tempfile.mkdtemp(prefix="singleflight-verify-"))
os.environ["CRAWLERHUB_DB"] = str(TEMP / "verify.db")
os.environ["CRAWLERHUB_LOG_DIR"] = str(TEMP / "logs")
os.environ["CRAWLERHUB_OUTPUT"] = str(TEMP / "output")
sys.path.insert(0, str(BACKEND))

from app.common.errors import BizError  # noqa: E402
from app.common.logger import setup_logging  # noqa: E402
from app.db.base import init_db, session_scope  # noqa: E402
from app.engine.crawler_engine import get_engine  # noqa: E402
from app.schemas.batch import BatchCreate  # noqa: E402
from app.schemas.data_source import DataSourceCreate  # noqa: E402
from app.services import batch_service, data_source_service  # noqa: E402

THREADS = 8
ROUNDS = 5


def main() -> int:
    setup_logging(TEMP / "logs", level=20)  # 便于核对「并发抢跑」分支是否真的走到
    init_db()
    engine = get_engine()
    # 只测创建期互斥：屏蔽真实调度，避免批次跑起来干扰判定
    engine.submit_batch = lambda *_a, **_k: True  # type: ignore[method-assign]

    with session_scope() as db:
        ds_id = data_source_service.create(
            db,
            DataSourceCreate(
                name="单飞验收源",
                type="text",
                homepage_url="https://example.com/list",
                config_json={"list_url": "https://example.com/list"},
                enabled=True,
            ),
        )

    print(f"8 线程 × {ROUNDS} 轮，数据源 #{ds_id}\n日志目录: {TEMP / 'logs'}")
    violations: list[str] = []

    for round_no in range(1, ROUNDS + 1):
        barrier = threading.Barrier(THREADS)
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
                            strategy="count",
                            strategy_params={"n": 1},
                        ),
                    )
                tag = "created"
            except BizError as exc:
                tag = f"rejected:{exc.code}"
                if exc.code == 3001 and "占用批次" in str(exc):
                    tag += "(含占用批次ID)"
            except Exception as exc:  # noqa: BLE001
                tag = f"error:{type(exc).__name__}:{exc}"
            with lock:
                outcomes.append(tag)

        threads = [threading.Thread(target=create_once) for _ in range(THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        created = outcomes.count("created")
        rejected = sum(1 for item in outcomes if item.startswith("rejected:3001"))
        errors = [item for item in outcomes if item.startswith("error")]
        print(
            f"  轮 {round_no}: 成功 {created} / 3001 拒绝 {rejected} / 异常 {len(errors)}"
            + (f"  → {errors[0]}" if errors else "")
        )
        if created != 1:
            violations.append(f"round{round_no}: created={created} outcomes={sorted(outcomes)}")
        if errors:
            violations.append(f"round{round_no}: errors={errors}")

        # 清理活跃批次，进入下一轮（模拟批次结束）
        from sqlalchemy import update

        from app.db.models import CrawlBatch

        with session_scope() as db:
            db.execute(update(CrawlBatch).values(status="success"))

    with session_scope() as db:
        active = db.execute(
            __import__("sqlalchemy").text(
                "select count(*) from crawl_batch where status in "
                "('pending','running','paused','paused_with_warning')"
            )
        ).scalar()

    print(f"\n最终活跃批次数：{active}（每轮结束后已置 success，应为 0）")
    if violations:
        print("FAILED:")
        for item in violations:
            print("  -", item)
        return 1
    print(f"PASSED：{THREADS} 线程 × {ROUNDS} 轮，每轮恰好 1 个成功，其余全部 3001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
