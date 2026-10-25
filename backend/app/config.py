"""全局配置：环境变量 + 结构性默认值 + 枚举字面量。

设计要点（ARCHITECTURE §11.5）：
- 枚举字面量集中在 ``E`` 中，与数据库 CHECK 约束保持同一份字符串；
- 可调默认值集中在 ``DEFAULTS``，运行期可被 ``app_setting`` 表覆盖（结构性上限除外）；
- 端口 / 路径全部来自环境变量，禁止硬编码。
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# 项目路径
# ---------------------------------------------------------------------------
# 当前文件位于 <项目根>/backend/app/config.py
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
BACKEND_ROOT: Final[Path] = PROJECT_ROOT / "backend"
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
LOG_DIR: Final[Path] = PROJECT_ROOT / "logs"
STATIC_DIR: Final[Path] = DATA_DIR / "static"
FRONTEND_DIST: Final[Path] = PROJECT_ROOT / "frontend" / "dist"

APP_NAME: Final[str] = "CrawlerHub"
APP_VERSION: Final[str] = "1.0.0"
APP_DESCRIPTION: Final[str] = (
    "CrawlerHub 通用爬虫平台后端：数据源 → 策略 → 批次 → 任务 → 产物 的一体化采集工作台"
)

API_PREFIX: Final[str] = "/api"


class E:
    """枚举字面量集合（DB CHECK 约束 / 前后端共用同一份字面量）。"""

    # ---- data_source.type ----
    TYPE_VIDEO: Final[str] = "video"
    TYPE_TEXT: Final[str] = "text"
    TYPE_IMAGE: Final[str] = "image"
    TYPES: Final[tuple[str, ...]] = (TYPE_VIDEO, TYPE_TEXT, TYPE_IMAGE)

    # ---- crawl_batch.status ----
    BATCH_PENDING: Final[str] = "pending"
    BATCH_RUNNING: Final[str] = "running"
    BATCH_PAUSED: Final[str] = "paused"
    BATCH_SUCCESS: Final[str] = "success"
    BATCH_SUCCESS_WITH_WARNING: Final[str] = "success_with_warning"
    BATCH_FAILED: Final[str] = "failed"
    BATCH_PAUSED_WITH_WARNING: Final[str] = "paused_with_warning"
    BATCH_STATUSES: Final[tuple[str, ...]] = (
        BATCH_PENDING,
        BATCH_RUNNING,
        BATCH_PAUSED,
        BATCH_SUCCESS,
        BATCH_SUCCESS_WITH_WARNING,
        BATCH_FAILED,
        BATCH_PAUSED_WITH_WARNING,
    )
    # 占用数据源（single-flight）的状态集合
    BATCH_BUSY_STATUSES: Final[tuple[str, ...]] = (
        BATCH_PENDING,
        BATCH_RUNNING,
        BATCH_PAUSED,
        BATCH_PAUSED_WITH_WARNING,
    )
    # 批次终态
    BATCH_TERMINAL_STATUSES: Final[tuple[str, ...]] = (
        BATCH_SUCCESS,
        BATCH_SUCCESS_WITH_WARNING,
        BATCH_FAILED,
    )

    # ---- crawl_batch.phase ----
    PHASE_PARSE: Final[str] = "parse"
    PHASE_EXECUTE: Final[str] = "execute"
    PHASE_DONE: Final[str] = "done"
    PHASES: Final[tuple[str, ...]] = (PHASE_PARSE, PHASE_EXECUTE, PHASE_DONE)

    # ---- crawl_task.status ----
    TASK_PENDING: Final[str] = "pending"
    TASK_RUNNING: Final[str] = "running"
    TASK_SUCCESS: Final[str] = "success"
    TASK_FAILED: Final[str] = "failed"
    TASK_PAUSED: Final[str] = "paused"
    TASK_SKIPPED: Final[str] = "skipped"
    TASK_STATUSES: Final[tuple[str, ...]] = (
        TASK_PENDING,
        TASK_RUNNING,
        TASK_SUCCESS,
        TASK_FAILED,
        TASK_PAUSED,
        TASK_SKIPPED,
    )

    # ---- crawl_batch.strategy ----
    STRATEGY_COUNT: Final[str] = "count"
    STRATEGY_PAGE: Final[str] = "page"
    STRATEGY_DATE: Final[str] = "date"
    STRATEGIES: Final[tuple[str, ...]] = (STRATEGY_COUNT, STRATEGY_PAGE, STRATEGY_DATE)

    # ---- task_log.level ----
    LOG_INFO: Final[str] = "INFO"
    LOG_WARN: Final[str] = "WARN"
    LOG_ERROR: Final[str] = "ERROR"
    LOG_LEVELS: Final[tuple[str, ...]] = (LOG_INFO, LOG_WARN, LOG_ERROR)

    # ---- artifact.type ----
    ARTIFACT_VIDEO: Final[str] = "video"
    ARTIFACT_TEXT: Final[str] = "text"
    ARTIFACT_PDF: Final[str] = "pdf"
    ARTIFACT_IMAGE: Final[str] = "image"
    ARTIFACT_TYPES: Final[tuple[str, ...]] = (
        ARTIFACT_VIDEO,
        ARTIFACT_TEXT,
        ARTIFACT_PDF,
        ARTIFACT_IMAGE,
    )

    # ---- artifact.status ----
    ARTIFACT_PROCESSING: Final[str] = "processing"
    ARTIFACT_SUCCESS: Final[str] = "success"
    ARTIFACT_FAILED: Final[str] = "failed"
    ARTIFACT_MISSING: Final[str] = "missing"
    ARTIFACT_STATUSES: Final[tuple[str, ...]] = (
        ARTIFACT_PROCESSING,
        ARTIFACT_SUCCESS,
        ARTIFACT_FAILED,
        ARTIFACT_MISSING,
    )

    # ---- 文字导出格式 ----
    FORMAT_TXT: Final[str] = "txt"
    FORMAT_PDF: Final[str] = "pdf"
    EXPORT_FORMATS: Final[tuple[str, ...]] = (FORMAT_TXT, FORMAT_PDF)

    # ---- 健康度等级 ----
    HEALTH_HEALTHY: Final[str] = "healthy"
    HEALTH_SUB_HEALTHY: Final[str] = "sub_healthy"
    HEALTH_UNHEALTHY: Final[str] = "unhealthy"
    HEALTH_UNKNOWN: Final[str] = "unknown"


#: 可被 app_setting 覆盖的默认值（结构性上限不开放覆盖）
DEFAULTS: Final[dict[str, int]] = {
    "max_threads": 4,
    "max_threads_limit": 32,
    "retry.max_attempts": 3,
    "retry.base_interval": 1,
    "health.refresh_interval": 3600,
    "disk.min_free_mb": 500,
    "queue.max_pending": 5000,
    "pause.timeout_s": 30,
    "script.timeout_s": 60,
    "segment.concurrency": 4,
    "http.timeout_s": 15,
    # 传输层默认不重试：自动重试统一由 TaskScheduler 负责（退避 1s×2^(n-1) + attempt_count 递增），
    # 避免「HTTP 内部重试」与「任务级重试」叠加导致 attempt_count 与实际请求次数不一致。
    "http.retries": 0,
    "retry.backoff_cap_s": 30,
    "health.retry_sample_size": 20,
    "health.recency_days": 14,
    "strategy.max_pages": 50,
    "strategy.n_max": 9999,
    "strategy.pages_max": 500,
    "strategy.date_span_days": 365,
    "log.keep_days": 7,
    "avatar.max_bytes": 2 * 1024 * 1024,
    "temp.ttl_hours": 24,
}

#: app_setting 键名常量
SETTING_KEYS: Final[dict[str, str]] = {
    "nickname": "profile.nickname",
    "avatar": "profile.avatar",
    "email": "profile.email",
    "output_root": "output_root",
    "max_threads": "max_threads",
    "max_attempts": "retry.max_attempts",
    "base_interval": "retry.base_interval",
    "health_refresh": "health.refresh_interval",
    "schema_version": "_schema_version",
}


class Settings(BaseSettings):
    """进程级配置（来自环境变量，只读）。"""

    model_config = SettingsConfigDict(
        env_prefix="CRAWLERHUB_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("CRAWLERHUB_HOST", "CRAWLERHUB_BIND"),
    )
    port: int = Field(default=8000, validation_alias=AliasChoices("CRAWLERHUB_PORT"))
    db_path: str = Field(
        default=str(DATA_DIR / "crawlerhub.db"),
        validation_alias=AliasChoices("CRAWLERHUB_DB", "CRAWLERHUB_DB_PATH"),
    )
    output_root: str = Field(
        default=str(DATA_DIR / "output"),
        validation_alias=AliasChoices("CRAWLERHUB_OUTPUT", "CRAWLERHUB_OUTPUT_ROOT"),
    )
    log_dir: str = Field(
        default=str(LOG_DIR), validation_alias=AliasChoices("CRAWLERHUB_LOG_DIR")
    )
    version: str = Field(
        default=APP_VERSION, validation_alias=AliasChoices("CRAWLERHUB_VERSION")
    )
    cors_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]

    # ---- 派生路径 ----
    @property
    def db_file(self) -> Path:
        """SQLite 文件的绝对路径。"""
        return Path(self.db_path).expanduser().resolve()

    @property
    def output_dir(self) -> Path:
        """默认产物根目录的绝对路径（运行期可被 app_setting 覆盖）。"""
        return Path(self.output_root).expanduser().resolve()

    @property
    def log_path(self) -> Path:
        """日志目录绝对路径。"""
        return Path(self.log_dir).expanduser().resolve()

    @property
    def static_dir(self) -> Path:
        """静态资源目录（头像等）。"""
        return STATIC_DIR

    @property
    def frontend_dist(self) -> Path:
        """前端构建产物目录，存在时由后端静态托管。"""
        return FRONTEND_DIST


#: 全局唯一配置实例
settings: Final[Settings] = Settings()


def ensure_base_dirs() -> None:
    """确保基座所需目录存在（数据、日志、静态资源、默认产物根）。"""
    for path in (settings.db_file.parent, settings.log_path, STATIC_DIR, settings.output_dir):
        path.mkdir(parents=True, exist_ok=True)
