"""设置服务：app_setting 读写、运行期配置快照、目录可写性、日志清理、头像上传。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.disk import check_writable
from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.common.timeutil import days_ago_iso, now_iso
from app.config import DEFAULTS, SETTING_KEYS, settings
from app.db.models import AppSetting, TaskLog
from app.schemas.setting import (
    AvatarResp,
    HealthSettingPayload,
    ProfilePayload,
    RetryPayload,
    SettingsPayload,
    SettingsUpdate,
    TestPathResp,
)

logger = get_logger(__name__)

#: 允许的头像扩展名
AVATAR_EXTS = frozenset({"png", "jpg", "jpeg"})


@dataclass(frozen=True)
class RuntimeSettings:
    """引擎/下载器所需的最小运行期配置快照。"""

    output_root: str
    max_threads: int
    max_attempts: int
    base_interval: int
    health_refresh_interval: int


# ---------------------------------------------------------------------------
# 基础读写
# ---------------------------------------------------------------------------
def read_map(db: Session) -> dict[str, str]:
    """读取全部设置键值。"""
    rows = db.execute(select(AppSetting.key, AppSetting.value)).all()
    return {str(key): str(value) for key, value in rows}


def get_value(db: Session, key: str, default: str = "") -> str:
    """读取单个设置值。"""
    row = db.execute(select(AppSetting.value).where(AppSetting.key == key)).first()
    return str(row[0]) if row else default


def get_int(db: Session, key: str, default: int) -> int:
    """读取整型设置值（非法值回落默认）。"""
    raw = get_value(db, key, "")
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)


def set_value(db: Session, key: str, value: str) -> None:
    """写入/更新单个设置值（不提交，由调用方控制事务）。"""
    row = db.get(AppSetting, key)
    stamp = now_iso()
    if row is None:
        db.add(AppSetting(key=key, value=str(value), updated_at=stamp))
    else:
        row.value = str(value)
        row.updated_at = stamp


# ---------------------------------------------------------------------------
# 运行期快照
# ---------------------------------------------------------------------------
def get_runtime(db: Session) -> RuntimeSettings:
    """读取引擎运行期配置（每次调用都从 DB 取，保证「改设置后新批次立即生效」）。"""
    output_root = get_value(db, SETTING_KEYS["output_root"], str(settings.output_dir)) or str(
        settings.output_dir
    )
    max_threads = get_int(db, SETTING_KEYS["max_threads"], int(DEFAULTS["max_threads"]))
    max_threads = max(1, min(int(DEFAULTS["max_threads_limit"]), max_threads))
    max_attempts = get_int(db, SETTING_KEYS["max_attempts"], int(DEFAULTS["retry.max_attempts"]))
    base_interval = get_int(db, SETTING_KEYS["base_interval"], int(DEFAULTS["retry.base_interval"]))
    refresh = get_int(db, SETTING_KEYS["health_refresh"], int(DEFAULTS["health.refresh_interval"]))
    return RuntimeSettings(
        output_root=str(Path(output_root).expanduser()),
        max_threads=max_threads,
        max_attempts=max(1, max_attempts),
        base_interval=max(1, base_interval),
        health_refresh_interval=max(60, refresh),
    )


# ---------------------------------------------------------------------------
# 设置页
# ---------------------------------------------------------------------------
def get_settings(db: Session) -> SettingsPayload:
    """读取全量设置。"""
    runtime = get_runtime(db)
    return SettingsPayload(
        profile=ProfilePayload(
            nickname=get_value(db, SETTING_KEYS["nickname"], "采集者") or "采集者",
            avatar=get_value(db, SETTING_KEYS["avatar"], ""),
            email=get_value(db, SETTING_KEYS["email"], ""),
        ),
        output_root=runtime.output_root,
        max_threads=runtime.max_threads,
        retry=RetryPayload(
            max_attempts=runtime.max_attempts, base_interval=runtime.base_interval
        ),
        health=HealthSettingPayload(refresh_interval=runtime.health_refresh_interval),
    )


def update_settings(db: Session, payload: SettingsUpdate) -> SettingsPayload:
    """更新设置（部分字段），输出根目录需可写否则 5002。"""
    if payload.output_root is not None:
        target = str(payload.output_root).strip()
        if not target:
            raise BizError(ErrCode.PARAM_INVALID, "输出根目录不能为空")
        ok, errno_code, reason = check_writable(target)
        if not ok:
            raise BizError(
                ErrCode.PATH_NOT_WRITABLE,
                f"输出根目录不可写：{reason or target}",
                retryable=False,
                detail=f"errno={errno_code}",
            )
        set_value(db, SETTING_KEYS["output_root"], str(Path(target).expanduser().resolve()))

    if payload.max_threads is not None:
        limit = int(DEFAULTS["max_threads_limit"])
        if not 1 <= int(payload.max_threads) <= limit:
            raise BizError(ErrCode.PARAM_INVALID, f"最大线程数需在 1-{limit} 之间")
        set_value(db, SETTING_KEYS["max_threads"], str(int(payload.max_threads)))

    if payload.profile is not None:
        set_value(db, SETTING_KEYS["nickname"], payload.profile.nickname or "采集者")
        set_value(db, SETTING_KEYS["avatar"], payload.profile.avatar or "")
        set_value(db, SETTING_KEYS["email"], payload.profile.email or "")

    if payload.retry is not None:
        set_value(db, SETTING_KEYS["max_attempts"], str(int(payload.retry.max_attempts)))
        set_value(db, SETTING_KEYS["base_interval"], str(int(payload.retry.base_interval)))

    if payload.health is not None:
        set_value(db, SETTING_KEYS["health_refresh"], str(int(payload.health.refresh_interval)))

    db.commit()
    logger.info("设置已更新")
    return get_settings(db)


def test_path(path: str) -> TestPathResp:
    """测试目录可写性，返回 ``{writable, errno, reason}``。"""
    target = str(path or "").strip()
    if not target:
        return TestPathResp(writable=False, errno=None, reason="路径不能为空")
    ok, errno_code, reason = check_writable(target)
    return TestPathResp(writable=ok, errno=errno_code, reason=reason)


def purge_logs(db: Session, keep_days: int) -> int:
    """清理 N 天前的任务日志，返回删除条数。"""
    days = max(0, int(keep_days))
    cutoff = days_ago_iso(days)
    result = db.execute(delete(TaskLog).where(TaskLog.created_at < cutoff))
    deleted = int(result.rowcount or 0)
    db.commit()
    logger.info("清理 %s 天前任务日志 %s 条", days, deleted)
    return deleted


def save_avatar(content: bytes, filename: str) -> AvatarResp:
    """保存头像（≤2MB，png/jpg），返回可访问 URL。"""
    max_bytes = int(DEFAULTS["avatar.max_bytes"])
    if len(content) > max_bytes:
        raise BizError(
            ErrCode.FILE_TOO_LARGE, f"头像不能超过 {max_bytes // (1024 * 1024)}MB"
        )
    suffix = Path(str(filename or "")).suffix.lower().lstrip(".")
    if suffix == "jpeg":
        suffix = "jpg"
    if suffix not in AVATAR_EXTS:
        raise BizError(ErrCode.FILE_FORMAT, "头像仅支持 png / jpg 格式")
    if not content:
        raise BizError(ErrCode.FILE_FORMAT, "头像内容为空")

    directory = settings.static_dir / "avatars"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{suffix}"
    target = directory / name
    target.write_bytes(content)
    logger.info("头像已保存：%s", target)
    return AvatarResp(url=f"/static/avatars/{name}")


def persist_avatar(db: Session, url: str) -> None:
    """把头像 URL 写入设置。"""
    set_value(db, SETTING_KEYS["avatar"], url)
    db.commit()
