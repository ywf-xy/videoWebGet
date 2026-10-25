"""种子数据：首启写入 8 个默认设置键（幂等，已存在则不覆盖）。"""

from __future__ import annotations

from sqlalchemy import select

from app.common.logger import get_logger
from app.common.timeutil import now_iso
from app.config import DEFAULTS, SETTING_KEYS, settings
from app.db.base import session_scope
from app.db.models import AppSetting

logger = get_logger(__name__)


def default_settings() -> dict[str, str]:
    """内置设置键的默认值。"""
    return {
        SETTING_KEYS["nickname"]: "采集者",
        SETTING_KEYS["avatar"]: "",
        SETTING_KEYS["email"]: "",
        SETTING_KEYS["output_root"]: str(settings.output_dir),
        SETTING_KEYS["max_threads"]: str(DEFAULTS["max_threads"]),
        SETTING_KEYS["max_attempts"]: str(DEFAULTS["retry.max_attempts"]),
        SETTING_KEYS["base_interval"]: str(DEFAULTS["retry.base_interval"]),
        SETTING_KEYS["health_refresh"]: str(DEFAULTS["health.refresh_interval"]),
    }


def run() -> int:
    """写入缺失的默认键，返回新增数量。"""
    created = 0
    with session_scope() as db:
        existing = {str(key) for (key,) in db.execute(select(AppSetting.key)).all()}
        stamp = now_iso()
        for key, value in default_settings().items():
            if key in existing:
                continue
            db.add(AppSetting(key=key, value=value, updated_at=stamp))
            created += 1
    if created:
        logger.info("种子数据：写入默认设置 %s 项", created)
    return created
