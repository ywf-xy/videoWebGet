"""系统 API：系统信息 / 运行指标 / 健康检查。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.common import Resp, ok
from app.schemas.setting import HealthCheckResp, MetricsResp, SystemInfoResp
from app.services import system_service

router = APIRouter(tags=["system"])


@router.get("/system/info", response_model=Resp[SystemInfoResp], summary="系统信息")
def get_system_info(db: SessionDep) -> dict:
    """版本 / Python / DB 路径与大小 / 输出根目录 / ffmpeg / 线程占用。"""
    return ok(system_service.get_info(db))


@router.get("/system/metrics", response_model=Resp[MetricsResp], summary="运行指标")
def get_system_metrics() -> dict:
    """CPU / 内存 / 线程 / uptime（3s 轮询，单次 <100ms）。"""
    return ok(system_service.get_metrics())


@router.get("/health", response_model=Resp[HealthCheckResp], summary="健康检查")
def health() -> dict:
    """进程存活检查。"""
    return ok(system_service.health_check())
