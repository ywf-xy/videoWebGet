"""健康度计算（PRD 9.6）。

``success_rate = 近 20 次 success 数 / 近 20 次总数``
``recency = clamp(1 - days_since_last_success / 14, 0, 1)``
``health = round(100 * (0.7 * success_rate + 0.3 * recency))``

无任务记录 → ``None``（前端显示「未知」灰色）；分级：≥80 绿 / 60-79 黄 / <60 红。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.common.timeutil import days_since
from app.config import DEFAULTS, E

#: 采样窗口大小
SAMPLE_SIZE: Final[int] = int(DEFAULTS["health.retry_sample_size"])
#: 衰减天数
RECENCY_DAYS: Final[float] = float(DEFAULTS["health.recency_days"])
#: 成功率权重
SUCCESS_WEIGHT: Final[float] = 0.7
#: 新鲜度权重
RECENCY_WEIGHT: Final[float] = 0.3
#: 健康 / 亚健康阈值
HEALTHY_THRESHOLD: Final[int] = 80
SUB_HEALTHY_THRESHOLD: Final[int] = 60


class HealthCalculator:
    """健康度纯函数集合（无 DB 依赖，便于单测）。"""

    @staticmethod
    def success_rate(statuses: Sequence[str]) -> float | None:
        """近 N 次任务成功率；无样本返回 None。"""
        sample = [str(item) for item in statuses if item is not None]
        if not sample:
            return None
        successes = sum(1 for item in sample if item == E.TASK_SUCCESS)
        return round(successes / len(sample), 4)

    @classmethod
    def compute(cls, statuses: Sequence[str], last_success_at: str | None) -> int | None:
        """计算健康分（0-100），无样本返回 None。"""
        rate = cls.success_rate(statuses)
        if rate is None:
            return None
        elapsed = days_since(last_success_at)
        recency = 0.0 if elapsed is None else max(0.0, min(1.0, 1.0 - elapsed / RECENCY_DAYS))
        score = 100.0 * (SUCCESS_WEIGHT * rate + RECENCY_WEIGHT * recency)
        return max(0, min(100, int(round(score))))

    @staticmethod
    def level(score: int | None) -> str:
        """健康度分级。"""
        if score is None:
            return E.HEALTH_UNKNOWN
        if score >= HEALTHY_THRESHOLD:
            return E.HEALTH_HEALTHY
        if score >= SUB_HEALTHY_THRESHOLD:
            return E.HEALTH_SUB_HEALTHY
        return E.HEALTH_UNHEALTHY
