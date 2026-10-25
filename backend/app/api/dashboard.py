"""首页统计 API（四模块各自独立接口，单卡失败不影响其他卡）。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.schemas.common import Resp, ok
from app.schemas.dashboard import HealthSourceItem, OverviewResp, TrendResp
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=Resp[OverviewResp], summary="首页概览")
def get_overview(db: SessionDep) -> dict:
    """健康源数/总数、今日/本周/本月采集量、运行中批次。"""
    return ok(dashboard_service.overview(db))


@router.get("/trend", response_model=Resp[TrendResp], summary="采集量趋势")
def get_trend(
    db: SessionDep,
    granularity: str = Query("day", description="day | week | month"),
) -> dict:
    """三粒度趋势：day=按小时、week/month=按天。"""
    return ok(dashboard_service.trend(db, granularity))


@router.get("/health", response_model=Resp[list[HealthSourceItem]], summary="数据源健康度")
def get_health(db: SessionDep, order: str = Query("asc", description="asc | desc")) -> dict:
    """健康度列表（按分数排序，无记录为 null）。"""
    return ok(dashboard_service.health_list(db, order))
