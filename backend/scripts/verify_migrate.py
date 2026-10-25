"""迁移三场景验证（一次性脚本，不入库）：空库 / 老库无索引+脏数据 / 中间版本旧索引。

用法：cd backend && .venv/Scripts/python.exe <本文件路径>
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]  # backend/
PY = str(BACKEND / ".venv" / "Scripts" / "python.exe")

CHILD = r'''
import os, sys
sys.path.insert(0, r"{backend}")
from app.common.logger import setup_logging
setup_logging(r"{logdir}", level=20)
from app.db.base import init_db
init_db()
import sqlite3
con = sqlite3.connect(r"{db}")
print("IDX:", sorted(r[0] for r in con.execute(
    "select name from sqlite_master where type='index' and name like 'uq_%'")))
print("BATCH:", con.execute("select count(*) from crawl_batch where status in "
      "('pending','running','paused','paused_with_warning')").fetchone()[0], "活跃批次")
print("BATCH_CLOSED:", con.execute("select count(*) from crawl_batch where error_code='3001'").fetchone()[0])
print("ART:", con.execute("select count(*) from artifact").fetchone()[0], "条产物")
print("ART_ROWS:", con.execute("select id, task_id, status, "
      "case when path='' then 'EMPTY' else 'HAS_PATH' end from artifact order by id").fetchall())
'''


def run_child(db: Path, logdir: Path) -> str:
    script = CHILD.format(backend=str(BACKEND), db=str(db), logdir=str(logdir))
    env = dict(os.environ)
    env["CRAWLERHUB_DB"] = str(db)
    env["CRAWLERHUB_LOG_DIR"] = str(logdir)
    env["CRAWLERHUB_OUTPUT"] = str(db.parent / "output")
    env["PYTHONPATH"] = str(BACKEND)
    result = subprocess.run(
        [PY, "-W", "ignore", "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(BACKEND),
    )
    out = (result.stdout or "") + (result.stderr or "")
    lines = [ln for ln in out.splitlines() if ln.startswith(("IDX:", "BATCH", "ART")) or "迁移" in ln]
    return "\n".join(lines)


def build_old_db(db: Path) -> None:
    """模拟修复前的库：无任何唯一索引，且存在两类脏数据。"""
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE data_source (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL,
            category TEXT, homepage_url TEXT NOT NULL, alt_urls JSON, current_url TEXT,
            script TEXT, script_entry TEXT, config_json JSON, is_novel INTEGER, enabled INTEGER,
            health_score INTEGER, success_rate_20 FLOAT, last_success_at TEXT, last_crawled_at TEXT,
            total_items INTEGER, cursor_last_item_no INTEGER, cursor_last_page INTEGER,
            cursor_last_success_date TEXT, notes TEXT, is_deleted INTEGER,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE crawl_batch (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_source_id INTEGER NOT NULL,
            strategy TEXT NOT NULL, strategy_params JSON, export_format TEXT, status TEXT NOT NULL,
            phase TEXT NOT NULL, total_tasks INTEGER, done_tasks INTEGER, failed_tasks INTEGER,
            skipped_tasks INTEGER, threads INTEGER, request_url TEXT, cursor_before JSON,
            cursor_after JSON, error_code TEXT, error_msg TEXT, warnings JSON,
            pause_requested_at TEXT, started_at TEXT, finished_at TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE crawl_task (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL,
            data_source_id INTEGER NOT NULL, seq_no INTEGER, title TEXT, source_url TEXT,
            payload JSON, status TEXT, attempt_count INTEGER, error_code TEXT, error_msg TEXT,
            step_total INTEGER, step_done INTEGER, duration_ms INTEGER, started_at TEXT,
            finished_at TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE artifact (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            task_result_id INTEGER, data_source_id INTEGER NOT NULL, data_source_name TEXT,
            type TEXT, name TEXT, category TEXT, path TEXT, size INTEGER, status TEXT,
            error_msg TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE app_setting (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        """
    )
    stamp = "2026-10-25T10:00:00.000+08:00"
    con.execute(
        "INSERT INTO data_source (id,name,type,homepage_url,is_novel,enabled,is_deleted,"
        "created_at,updated_at) VALUES (1,'脏数据源','text','https://e.com',0,1,0,?,?)",
        (stamp, stamp),
    )
    # 同一数据源 3 个活跃批次（应保留 id 最大者，其余置 failed）
    for batch_id, status in ((1, "running"), (2, "paused"), (3, "running")):
        con.execute(
            "INSERT INTO crawl_batch (id,data_source_id,strategy,strategy_params,status,phase,"
            "threads,created_at,updated_at) VALUES (?,1,'count','{}',?,'execute',4,?,?)",
            (batch_id, status, stamp, stamp),
        )
    con.execute(
        "INSERT INTO crawl_task (id,batch_id,data_source_id,seq_no,title,source_url,payload,status,"
        "created_at,updated_at) VALUES (1,3,1,1,'第001章','https://e.com/1','{}','success',?,?)",
        (stamp, stamp),
    )
    # 同一 (task_id,name) 3 条产物：一条有 path（较旧），两条 processing 空 path（较新）
    rows = [
        (1, 1, "第001章", "/out/a.txt", 12, "success", "2026-10-25T10:00:01.000+08:00"),
        (2, 1, "第001章", "", 0, "processing", "2026-10-25T10:00:03.000+08:00"),
        (3, 1, "第001章", "", 0, "processing", "2026-10-25T10:00:02.000+08:00"),
    ]
    for artifact_id, task_id, name, path, size, status, created in rows:
        con.execute(
            "INSERT INTO artifact (id,task_id,data_source_id,data_source_name,type,name,path,size,"
            "status,created_at,updated_at) VALUES (?,?,1,'脏数据源','text',?,?,?,?,?,?)",
            (artifact_id, task_id, name, path, size, status, created, created),
        )
    con.commit()
    con.close()


def build_intermediate_db(db: Path) -> None:
    """模拟我上一版实现：artifact 上有旧的 uq_artifact_task(task_id) 索引，无脏数据。"""
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE artifact (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            task_result_id INTEGER, data_source_id INTEGER NOT NULL, data_source_name TEXT,
            type TEXT, name TEXT, category TEXT, path TEXT, size INTEGER, status TEXT,
            error_msg TEXT, created_at TEXT, updated_at TEXT);
        CREATE UNIQUE INDEX uq_artifact_task ON artifact(task_id);
        CREATE TABLE crawl_batch (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_source_id INTEGER NOT NULL,
            strategy TEXT NOT NULL, strategy_params JSON, export_format TEXT, status TEXT NOT NULL,
            phase TEXT NOT NULL, total_tasks INTEGER, done_tasks INTEGER, failed_tasks INTEGER,
            skipped_tasks INTEGER, threads INTEGER, request_url TEXT, cursor_before JSON,
            cursor_after JSON, error_code TEXT, error_msg TEXT, warnings JSON,
            pause_requested_at TEXT, started_at TEXT, finished_at TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE crawl_task (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL,
            data_source_id INTEGER NOT NULL, seq_no INTEGER, title TEXT, source_url TEXT,
            payload JSON, status TEXT, attempt_count INTEGER, error_code TEXT, error_msg TEXT,
            step_total INTEGER, step_done INTEGER, duration_ms INTEGER, started_at TEXT,
            finished_at TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE app_setting (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        """
    )
    con.commit()
    con.close()


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="migrate-verify-"))
    print(f"工作目录: {root}\n")

    print("=" * 72)
    print("场景 A：空库（create_all 直接建索引，migrate 无需去重）")
    print("=" * 72)
    db_a = root / "empty" / "crawlerhub.db"
    db_a.parent.mkdir(parents=True, exist_ok=True)
    print(run_child(db_a, root / "logs-a"))

    print("\n" + "=" * 72)
    print("场景 B：老库（无唯一索引 + 同源 3 活跃批次 + 同任务同名 3 产物）")
    print("=" * 72)
    db_b = root / "dirty" / "crawlerhub.db"
    db_b.parent.mkdir(parents=True, exist_ok=True)
    build_old_db(db_b)
    print(run_child(db_b, root / "logs-b"))

    print("\n" + "=" * 72)
    print("场景 C：中间版本（存在旧的 uq_artifact_task，应 DROP 后按新键重建）")
    print("=" * 72)
    db_c = root / "intermediate" / "crawlerhub.db"
    db_c.parent.mkdir(parents=True, exist_ok=True)
    build_intermediate_db(db_c)
    print(run_child(db_c, root / "logs-c"))

    print("\n幂等性：对场景 B 的库再跑一次 migrate（不应重复清理/报错）")
    print(run_child(db_b, root / "logs-b2"))

    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
