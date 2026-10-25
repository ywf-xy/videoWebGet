"""API 路由层：仅做参数校验 + 统一响应包装，禁止在此层做 IO / 抓取。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import artifact, batch, dashboard, data_source, setting, system, task
from app.config import API_PREFIX


def build_router() -> APIRouter:
    """汇总全部子路由，统一挂载在 ``/api`` 前缀下。"""
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(dashboard.router)
    router.include_router(data_source.router)
    router.include_router(batch.router)
    router.include_router(task.router)
    router.include_router(artifact.router)
    router.include_router(setting.router)
    router.include_router(system.router)
    return router


__all__ = [
    "artifact",
    "batch",
    "build_router",
    "dashboard",
    "data_source",
    "setting",
    "system",
    "task",
]
