"""版本化迁移（自研 12 行级别，不引入 alembic）。

- 版本号存于 ``app_setting`` 的 ``_schema_version`` 键（不额外建表，保持 7 张表）；
- ``run()`` 幂等：已是最新版本时只做列补齐检查，不产生副作用；
- 新增列/索引统一走 ``_ensure_column``，保证老库升级不丢数据。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.common.timeutil import now_iso
from app.config import SETTING_KEYS
from app.db.base import session_scope

logger = get_logger(__name__)

#: 当前 schema 版本
SCHEMA_VERSION: int = 1

_VERSION_KEY = SETTING_KEYS["schema_version"]

#: 追加列定义：(表名, 列名, 列定义)
_EXTRA_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # 文字导出格式（txt/pdf）需随批次持久化，便于恢复/重试时保持用户选择
    ("crawl_batch", "export_format", "TEXT"),
)

#: 追加索引定义：(索引名, 建索引 DDL, 去重函数名)
#: - ``uq_batch_active``：single-flight 的数据库级兜底（BUG-02）
#: - ``uq_artifact_task_name``：同任务同名产物唯一（BUG-03，键含 name 以兼容「一图一产物」演进）
#: - ``_LEGACY_INDEXES``：早期实现留下的更严索引，升级时先删再按新键重建
_EXTRA_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "uq_batch_active",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_active ON crawl_batch(data_source_id) "
        "WHERE status IN ('pending','running','paused','paused_with_warning')",
        "_dedupe_active_batches",
    ),
    (
        "uq_artifact_task_name",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_artifact_task_name ON artifact(task_id, name)",
        "_dedupe_artifacts",
    ),
)

#: 需要清除的历史索引（旧实现建过，键比新方案更严/不同）
_LEGACY_INDEXES: tuple[str, ...] = ("uq_artifact_task",)


def _table_exists(db: Session, table: str) -> bool:
    """判断表是否存在。"""
    row = db.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name = :name"),
        {"name": table},
    ).fetchone()
    return row is not None


def _table_columns(db: Session, table: str) -> set[str]:
    """读取表的现有列名（表不存在时返回空集合）。"""
    if not _table_exists(db, table):
        return set()
    rows = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {str(row[1]) for row in rows}


def _ensure_column(db: Session, table: str, column: str, ddl: str) -> bool:
    """补列（幂等），返回是否实际新增。"""
    if column in _table_columns(db, table):
        return False
    db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    logger.info("迁移：为表 %s 追加列 %s", table, column)
    return True


def _read_version(db: Session) -> int:
    """读取当前 schema 版本，无记录返回 0。"""
    row = db.execute(
        text("SELECT value FROM app_setting WHERE key = :key"), {"key": _VERSION_KEY}
    ).fetchone()
    if not row:
        return 0
    try:
        return int(str(row[0]))
    except (TypeError, ValueError):
        return 0


def _write_version(db: Session, version: int) -> None:
    """写入 schema 版本（upsert）。"""
    exists = db.execute(
        text("SELECT 1 FROM app_setting WHERE key = :key"), {"key": _VERSION_KEY}
    ).fetchone()
    if exists:
        db.execute(
            text("UPDATE app_setting SET value = :value, updated_at = :ts WHERE key = :key"),
            {"value": str(version), "ts": now_iso(), "key": _VERSION_KEY},
        )
    else:
        db.execute(
            text("INSERT INTO app_setting (key, value, updated_at) VALUES (:key, :value, :ts)"),
            {"key": _VERSION_KEY, "value": str(version), "ts": now_iso()},
        )


def _migrate_v1(db: Session) -> None:
    """v1：初始版本，表结构由 ``Base.metadata.create_all`` 建立。"""


#: 版本 → 迁移函数
_MIGRATIONS: dict[int, Callable[[Session], None]] = {
    1: _migrate_v1,
}


def _index_exists(db: Session, name: str) -> bool:
    """判断索引是否已存在。"""
    row = db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='index' AND name = :name"),
        {"name": name},
    ).fetchone()
    return row is not None


def _drop_index(db: Session, name: str) -> bool:
    """删除历史索引（幂等），返回是否实际删除。"""
    if not _index_exists(db, name):
        return False
    db.execute(text(f"DROP INDEX {name}"))
    logger.warning("迁移：已删除历史索引 %s（将由新键索引替代）", name)
    return True


def _dedupe_active_batches(db: Session) -> int:
    """清理「同一数据源多个活跃批次」的历史脏数据。

    保留 id 最大（最近发起）的那条仍为活跃，其余置为 ``failed`` 并写清原因；
    返回被关闭的批次数，逐条写 WARN 日志便于回溯。
    """
    if not _table_exists(db, "crawl_batch"):
        return 0
    rows = db.execute(
        text(
            "SELECT id, data_source_id, status, created_at FROM crawl_batch "
            "WHERE status IN ('pending','running','paused','paused_with_warning') "
            "ORDER BY data_source_id ASC, id DESC"
        )
    ).fetchall()
    keep: dict[int, int] = {}
    closed: list[tuple[int, int]] = []
    for row in rows:
        batch_id = int(row[0])
        ds_id = int(row[1])
        if ds_id in keep:
            closed.append((batch_id, ds_id))
        else:
            keep[ds_id] = batch_id

    if not closed:
        return 0

    stamp = now_iso()
    for batch_id, ds_id in closed:
        db.execute(
            text(
                "UPDATE crawl_batch SET status = 'failed', error_code = '3001', "
                "error_msg = :msg, finished_at = :ts, updated_at = :ts, pause_requested_at = NULL "
                "WHERE id = :id"
            ),
            {
                "msg": (
                    f"迁移去重：数据源 #{ds_id} 同时存在多个活跃批次，"
                    f"已关闭较早的 #{batch_id}（保留 #{keep[ds_id]}）"
                ),
                "ts": stamp,
                "id": batch_id,
            },
        )
        logger.warning(
            "迁移去重：关闭重复活跃批次 #%s（数据源 #%s，保留 #%s）",
            batch_id,
            ds_id,
            keep[ds_id],
        )
    return len(closed)


def _dedupe_artifacts(db: Session) -> int:
    """清理「同一任务同名产物」的历史重复行（BUG-03 遗留僵尸）。

    保留优先级：``path`` 非空 > ``created_at`` 更晚 > ``id`` 更大；
    其余删除并逐条 WARN（含 id / task_id / name / path 摘要）。
    """
    if not _table_exists(db, "artifact"):
        return 0
    rows = db.execute(
        text(
            "SELECT id, task_id, name, path, status, created_at FROM artifact "
            "ORDER BY task_id ASC, name ASC, "
            "(CASE WHEN path IS NOT NULL AND path <> '' THEN 0 ELSE 1 END) ASC, "
            "created_at DESC, id DESC"
        )
    ).fetchall()
    keep: dict[tuple[int, str], int] = {}
    dropped: list[tuple[int, int, str, str, str]] = []
    for row in rows:
        artifact_id = int(row[0])
        key = (int(row[1]), str(row[2]))
        if key in keep:
            dropped.append((artifact_id, int(row[1]), str(row[2]), str(row[3] or ""), str(row[4])))
        else:
            keep[key] = artifact_id

    if not dropped:
        return 0

    for chunk_start in range(0, len(dropped), 500):
        chunk = dropped[chunk_start : chunk_start + 500]
        ids = ", ".join(str(item[0]) for item in chunk)
        db.execute(text(f"DELETE FROM artifact WHERE id IN ({ids})"))

    for artifact_id, task_id, name, path, status in dropped:
        logger.warning(
            "迁移去重：删除重复产物 #%s（task=#%s，name=%r，path=%r，status=%s）",
            artifact_id,
            task_id,
            name,
            path[:80],
            status,
        )
    return len(dropped)


def _ensure_index(db: Session, name: str, ddl: str, dedupe_name: str) -> bool:
    """补唯一索引（幂等）：先做存量去重，再建索引；去重后仍失败则告警跳过。"""
    if _index_exists(db, name):
        return False
    dedupe = globals().get(dedupe_name)
    removed = 0
    if callable(dedupe):
        removed = int(dedupe(db) or 0)
    if removed:
        logger.warning("迁移：为创建唯一索引 %s，已清理 %s 条重复/冲突数据", name, removed)
    try:
        db.execute(text(ddl))
    except Exception as exc:  # noqa: BLE001 - 迁移不得阻断启动
        logger.error("迁移：创建索引 %s 失败（已跳过，服务继续启动）：%s", name, exc)
        return False
    logger.info("迁移：已创建索引 %s", name)
    return True


def run() -> int:
    """执行迁移，返回最终 schema 版本。"""
    with session_scope() as db:
        current = _read_version(db)
        if current < SCHEMA_VERSION:
            for step in range(current + 1, SCHEMA_VERSION + 1):
                handler = _MIGRATIONS.get(step)
                if handler is not None:
                    handler(db)
                _write_version(db, step)
                logger.info("迁移：schema 升级到 v%s", step)
        # 列补齐（幂等，兼容 create_all 之前的旧库）
        for table, column, ddl in _EXTRA_COLUMNS:
            _ensure_column(db, table, column, ddl)
        # 清理历史索引（键已变更），再补齐唯一索引（含存量去重）
        for legacy in _LEGACY_INDEXES:
            _drop_index(db, legacy)
        for name, ddl, dedupe_name in _EXTRA_INDEXES:
            _ensure_index(db, name, ddl, dedupe_name)
        return _read_version(db)
