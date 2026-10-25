"""系统信息服务：版本 / Python / 数据库 / 输出根目录 / ffmpeg / 线程 / 指标。"""

from __future__ import annotations

import platform
import time
from pathlib import Path

import psutil
from sqlalchemy.orm import Session

from app.common.disk import safe_size
from app.common.logger import get_logger
from app.config import APP_VERSION, settings
from app.downloader.ffmpeg import ffmpeg_info
from app.engine.crawler_engine import get_engine
from app.schemas.setting import (
    FfmpegInfo,
    HealthCheckResp,
    MemoryInfo,
    MetricsResp,
    SystemInfoResp,
    ThreadInfo,
)
from app.services.setting_service import get_runtime

logger = get_logger(__name__)

#: 进程启动时间（用于 uptime）
START_TIME: float = time.time()


def _thread_info() -> ThreadInfo:
    """线程占用（活跃任务数 / 全局上限）。"""
    stat = get_engine().thread_stat()
    return ThreadInfo(active=stat.active, max=stat.max)


def get_info(db: Session) -> SystemInfoResp:
    """系统信息（设置页系统信息区块）。"""
    runtime = get_runtime(db)
    db_file = Path(settings.db_file)
    info = ffmpeg_info()
    return SystemInfoResp(
        version=APP_VERSION,
        python=f"{platform.python_version()} ({platform.system()} {platform.machine()})",
        db_path=str(db_file),
        db_size=safe_size(db_file),
        output_root=runtime.output_root,
        ffmpeg=FfmpegInfo(
            available=bool(info.get("available")),
            version=str(info.get("version") or "") or None,
            path=str(info.get("path") or "") or None,
        ),
        threads=_thread_info(),
    )


def get_metrics() -> MetricsResp:
    """系统指标（CPU / 内存 / 线程 / uptime），单次 < 100ms。"""
    memory = psutil.virtual_memory()
    return MetricsResp(
        cpu_percent=float(psutil.cpu_percent(interval=None)),
        memory=MemoryInfo(
            used=int(memory.used),
            total=int(memory.total),
            percent=round(float(memory.percent), 1),
        ),
        threads=_thread_info(),
        uptime_s=int(time.time() - START_TIME),
    )


def health_check() -> HealthCheckResp:
    """健康检查。"""
    return HealthCheckResp(status="ok", version=APP_VERSION)
