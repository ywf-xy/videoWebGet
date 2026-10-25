"""ORM 模型：7 张表（data_source / crawl_batch / crawl_task / task_result / task_log / artifact / app_setting）。

约定：时间字段为 TEXT 存 ISO 8601 本地时区；布尔用 INTEGER 0/1；JSON 用 TEXT（SQLAlchemy JSON 类型）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.timeutil import now_iso
from app.config import E
from app.db.base import Base


class DataSource(Base):
    """数据源：一个站点/栏目的采集配置单元。"""

    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    homepage_url: Mapped[str] = mapped_column(Text, nullable=False)
    alt_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    current_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_entry: Mapped[str] = mapped_column(Text, nullable=False, default="parse")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_novel: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success_rate_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_success_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_crawled_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_last_item_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_last_page: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_last_success_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    __table_args__ = (
        CheckConstraint("type IN ('video','text','image')", name="ck_ds_type"),
        Index(
            "uq_ds_name_url",
            "name",
            "homepage_url",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
        Index("ix_ds_type_enabled", "type", "enabled"),
        Index("ix_ds_health", "health_score"),
    )


class CrawlBatch(Base):
    """爬取批次：一次「数据源 + 策略」的执行实例。"""

    __tablename__ = "crawl_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_source.id"), nullable=False
    )
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    export_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=E.BATCH_PENDING)
    phase: Mapped[str] = mapped_column(Text, nullable=False, default=E.PHASE_PARSE)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    threads: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cursor_after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pause_requested_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    __table_args__ = (
        CheckConstraint("strategy IN ('count','page','date')", name="ck_batch_strategy"),
        CheckConstraint(
            "status IN ('pending','running','paused','success','success_with_warning',"
            "'failed','paused_with_warning')",
            name="ck_batch_status",
        ),
        Index("ix_batch_ds_status", "data_source_id", "status"),
        Index("ix_batch_status_created", "status", "created_at"),
        # single-flight 的数据库级兜底（PRD P0-15③ / §9.3）：
        # 同一数据源在「活跃状态」下只允许一条批次记录，避免「先 SELECT 再 INSERT」的并发竞态。
        Index(
            "uq_batch_active",
            "data_source_id",
            unique=True,
            sqlite_where=text(
                "status IN ('pending','running','paused','paused_with_warning')"
            ),
        ),
    )


class CrawlTask(Base):
    """爬取任务：单条内容（一个视频 / 一章 / 一个图集）的采集单元。"""

    __tablename__ = "crawl_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("crawl_batch.id"), nullable=False
    )
    data_source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=E.TASK_PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','success','failed','paused','skipped')",
            name="ck_task_status",
        ),
        Index("ix_task_batch_status", "batch_id", "status"),
        Index("ix_task_ds_created", "data_source_id", "created_at"),
        Index("ix_task_status", "status"),
    )


class TaskResult(Base):
    """任务结果：任务成功后的结构化产出（task_id 唯一，重试覆盖）。"""

    __tablename__ = "task_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("crawl_task.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)

    __table_args__ = (
        Index("uq_result_task", "task_id", unique=True),
        Index("ix_result_fp", "fingerprint"),
    )


class TaskLog(Base):
    """任务日志：批次级（task_id=NULL）与任务级。"""

    __tablename__ = "task_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(Text, nullable=False, default=E.LOG_INFO)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("level IN ('INFO','WARN','ERROR')", name="ck_log_level"),
        Index("ix_log_batch_id", "batch_id", "id"),
        Index("ix_log_task_id", "task_id", "id"),
        Index("ix_log_created", "created_at"),
    )


class Artifact(Base):
    """产物：任务成功后生成的文件实体（图片为目录）。"""

    __tablename__ = "artifact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    task_result_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    data_source_name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=E.ARTIFACT_PROCESSING)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    __table_args__ = (
        CheckConstraint(
            "type IN ('video','text','pdf','image')", name="ck_artifact_type"
        ),
        CheckConstraint(
            "status IN ('processing','success','failed','missing')",
            name="ck_artifact_status",
        ),
        Index(
            "ix_art_filter", "data_source_id", "type", "status", "created_at"
        ),
        Index("ix_art_created", "created_at"),
        Index("ix_art_name", "name"),
        Index("ix_art_task", "task_id"),
        # 同一任务下的同名产物只允许一条（幂等 upsert 的数据库级保证）：
        # 键取 (task_id, name) 而非单纯 task_id —— 当前实现是「1 图集 = 1 条 artifact
        # （path 指向图集目录）」，但保留 name 维度后，将来若改为「1 图 = 1 条 artifact」
        # 也无需再改索引。
        Index("uq_artifact_task_name", "task_id", "name", unique=True),
    )


class AppSetting(Base):
    """应用设置（键值对，值为字符串）。"""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)


__all__ = [
    "AppSetting",
    "Artifact",
    "CrawlBatch",
    "CrawlTask",
    "DataSource",
    "TaskLog",
    "TaskResult",
]
