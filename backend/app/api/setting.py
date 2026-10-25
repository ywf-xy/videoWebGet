"""设置 API：个人信息 / 采集设置 / 头像 / 目录测试 / 清理日志。"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.api.deps import SessionDep
from app.engine.crawler_engine import get_engine
from app.schemas.common import Resp, ok
from app.schemas.setting import (
    AvatarResp,
    PurgeLogsPayload,
    PurgeLogsResp,
    RebuildStatsResp,
    SettingsPayload,
    SettingsUpdate,
    TestPathPayload,
    TestPathResp,
)
from app.services import health_service, setting_service

router = APIRouter(prefix="/settings", tags=["setting"])


@router.get("", response_model=Resp[SettingsPayload], summary="读取设置")
def get_settings(db: SessionDep) -> dict:
    """返回全量设置（个人信息 / 输出根目录 / 线程数 / 重试 / 健康度）。"""
    return ok(setting_service.get_settings(db))


@router.put("", response_model=Resp[SettingsPayload], summary="保存设置")
def update_settings(db: SessionDep, payload: SettingsUpdate) -> dict:
    """部分字段更新；线程数越界 1001、目录不可写 5002。"""
    updated = setting_service.update_settings(db, payload)
    # 线程数变更后立即同步引擎并发上限（PRD 9.3 动态调整）
    get_engine().sync_limit()
    return ok(updated)


@router.post("/avatar", response_model=Resp[AvatarResp], summary="上传头像")
async def upload_avatar(db: SessionDep, file: UploadFile = File(...)) -> dict:
    """≤2MB、png/jpg；返回可访问 URL 并写入设置。"""
    content = await file.read()
    result = setting_service.save_avatar(content, file.filename or "avatar.png")
    setting_service.persist_avatar(db, result.url)
    return ok(result)


@router.post("/test-path", response_model=Resp[TestPathResp], summary="测试目录可写")
def test_path(payload: TestPathPayload) -> dict:
    """返回 ``{writable, errno, reason}``。"""
    return ok(setting_service.test_path(payload.path))


@router.post("/purge-logs", response_model=Resp[PurgeLogsResp], summary="清理历史任务日志")
def purge_logs(db: SessionDep, payload: PurgeLogsPayload) -> dict:
    """删除 keep_days 天前的任务日志，返回删除条数。"""
    return ok(PurgeLogsResp(deleted=setting_service.purge_logs(db, payload.keep_days)))


@router.post("/rebuild-stats", response_model=Resp[RebuildStatsResp], summary="重建统计缓存（健康度）")
def rebuild_stats(db: SessionDep) -> dict:
    """重算全部数据源的健康度与近 20 次成功率（设置页「危险操作」）。"""
    return ok(RebuildStatsResp(updated=health_service.refresh_all(db)))
