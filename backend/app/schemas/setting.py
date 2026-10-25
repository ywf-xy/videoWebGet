"""设置与系统信息 DTO。"""

from __future__ import annotations

from pydantic import Field

from app.config import DEFAULTS
from app.schemas.common import CamelModel


class ProfilePayload(CamelModel):
    """个人信息。"""

    nickname: str = "采集者"
    avatar: str = ""
    email: str = ""


class RetryPayload(CamelModel):
    """重试设置。"""

    max_attempts: int = Field(default=int(DEFAULTS["retry.max_attempts"]), ge=1, le=10)
    base_interval: int = Field(default=int(DEFAULTS["retry.base_interval"]), ge=1, le=60)


class HealthSettingPayload(CamelModel):
    """健康度刷新设置。"""

    refresh_interval: int = Field(default=int(DEFAULTS["health.refresh_interval"]), ge=60, le=86400)


class SettingsPayload(CamelModel):
    """全量设置。"""

    profile: ProfilePayload = Field(default_factory=ProfilePayload)
    output_root: str = ""
    max_threads: int = int(DEFAULTS["max_threads"])
    retry: RetryPayload = Field(default_factory=RetryPayload)
    health: HealthSettingPayload = Field(default_factory=HealthSettingPayload)


class SettingsUpdate(CamelModel):
    """设置更新入参（部分字段可选）。"""

    profile: ProfilePayload | None = None
    output_root: str | None = None
    max_threads: int | None = Field(default=None, ge=1, le=int(DEFAULTS["max_threads_limit"]))
    retry: RetryPayload | None = None
    health: HealthSettingPayload | None = None


class AvatarResp(CamelModel):
    """头像上传出参。"""

    url: str


class TestPathPayload(CamelModel):
    """目录可写性测试入参。"""

    path: str


class TestPathResp(CamelModel):
    """目录可写性测试出参。"""

    writable: bool = False
    errno: int | None = None
    reason: str | None = None


class PurgeLogsPayload(CamelModel):
    """清理日志入参。"""

    keep_days: int = Field(default=int(DEFAULTS["log.keep_days"]), ge=0, le=3650)


class PurgeLogsResp(CamelModel):
    """清理日志出参。"""

    deleted: int = 0


class RebuildStatsResp(CamelModel):
    """重建统计（健康度）出参。"""

    updated: int = 0


class FfmpegInfo(CamelModel):
    """ffmpeg 探测结果。"""

    available: bool = False
    version: str | None = None
    path: str | None = None


class ThreadInfo(CamelModel):
    """线程占用。"""

    active: int = 0
    max: int = 0


class DbInfo(CamelModel):
    """数据库信息。"""

    path: str = ""
    size: int = 0


class SystemInfoResp(CamelModel):
    """系统信息出参。"""

    version: str
    python: str
    db_path: str
    db_size: int = 0
    output_root: str = ""
    ffmpeg: FfmpegInfo = Field(default_factory=FfmpegInfo)
    threads: ThreadInfo = Field(default_factory=ThreadInfo)


class MemoryInfo(CamelModel):
    """内存信息（字节）。"""

    used: int = 0
    total: int = 0
    percent: float = 0.0


class MetricsResp(CamelModel):
    """系统指标出参。"""

    cpu_percent: float = 0.0
    memory: MemoryInfo = Field(default_factory=MemoryInfo)
    threads: ThreadInfo = Field(default_factory=ThreadInfo)
    uptime_s: int = 0


class HealthCheckResp(CamelModel):
    """健康检查出参。"""

    status: str = "ok"
    version: str = ""
