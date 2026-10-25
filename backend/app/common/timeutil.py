"""时间工具：全项目唯一的 ISO 8601 生成/解析入口（ARCHITECTURE §11.3）。

存库与传输格式固定为 ``yyyy-MM-ddTHH:mm:ss.SSS+08:00``（毫秒 + 时区偏移），
字符串定长可直接用于 SQLite 的范围比较与 ``substr`` 聚合。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final

#: 毫秒精度 + 时区偏移
ISO_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.%f%z"
DATE_FORMAT: Final[str] = "%Y-%m-%d"


def now() -> datetime:
    """当前本地时区（带 tzinfo）时间。"""
    return datetime.now().astimezone()


def now_iso() -> str:
    """当前时间的 ISO 8601 字符串（毫秒 + 时区偏移）。"""
    return to_iso(now())


def to_iso(value: datetime | None) -> str | None:
    """datetime → ISO 8601 字符串（本地时区、毫秒精度）。"""
    if value is None:
        return None
    local = value.astimezone() if value.tzinfo is not None else value.astimezone()
    offset = local.strftime("%z")  # 形如 +0800
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return (
        f"{local.strftime('%Y-%m-%dT%H:%M:%S')}."
        f"{local.microsecond // 1000:03d}{offset}"
    )


def parse_iso(value: str | None) -> datetime | None:
    """ISO 8601 字符串 → datetime，解析失败返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in (ISO_FORMAT, "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", DATE_FORMAT):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def today() -> date:
    """本地时区的今天。"""
    return now().date()


def today_str() -> str:
    """本地时区的今天（yyyy-MM-dd）。"""
    return today().strftime(DATE_FORMAT)


def date_to_str(value: date | datetime | None) -> str | None:
    """date / datetime → yyyy-MM-dd。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().strftime(DATE_FORMAT)
    return value.strftime(DATE_FORMAT)


def parse_date(value: str | None) -> date | None:
    """yyyy-MM-dd → date，失败返回 None。"""
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip()[:10], DATE_FORMAT).date()
    except ValueError:
        return None


def to_ts(value: str | None) -> float:
    """ISO 字符串 → Unix 时间戳（秒），解析失败返回 0.0。"""
    parsed = parse_iso(value)
    return parsed.timestamp() if parsed is not None else 0.0


def elapsed_ms(start_iso: str | None, end_iso: str | None = None) -> int:
    """两个 ISO 时间之间的毫秒差；end 缺省取当前时间。"""
    start = parse_iso(start_iso)
    if start is None:
        return 0
    end = parse_iso(end_iso) or now()
    if start.tzinfo is None or end.tzinfo is None:
        delta = end.replace(tzinfo=None) - start.replace(tzinfo=None)
    else:
        delta = end - start
    return max(0, int(delta.total_seconds() * 1000))


def day_start(value: datetime | None = None) -> datetime:
    """当天 00:00:00。"""
    base = value or now()
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def week_start(value: datetime | None = None) -> datetime:
    """本周（周一）00:00:00。"""
    start = day_start(value)
    return start - timedelta(days=start.weekday())


def month_start(value: datetime | None = None) -> datetime:
    """本月 1 日 00:00:00。"""
    start = day_start(value)
    return start.replace(day=1)


def day_start_iso(value: datetime | None = None) -> str:
    """当天 00:00:00 的 ISO 字符串。"""
    return to_iso(day_start(value)) or ""


def week_start_iso(value: datetime | None = None) -> str:
    """本周一 00:00:00 的 ISO 字符串。"""
    return to_iso(week_start(value)) or ""


def month_start_iso(value: datetime | None = None) -> str:
    """本月 1 日 00:00:00 的 ISO 字符串。"""
    return to_iso(month_start(value)) or ""


def hours_ago_iso(hours: int) -> str:
    """N 小时前的 ISO 字符串。"""
    return to_iso(now() - timedelta(hours=hours)) or ""


def days_ago_iso(days: int) -> str:
    """N 天前的 ISO 字符串。"""
    return to_iso(now() - timedelta(days=days)) or ""


def days_since(value: str | None) -> float | None:
    """距今经过的天数（用于健康度衰减），无记录返回 None。"""
    parsed = parse_iso(value)
    if parsed is None:
        return None
    current = now()
    if parsed.tzinfo is None:
        current = current.replace(tzinfo=None)
    return max(0.0, (current - parsed).total_seconds() / 86400.0)


def now_ms() -> int:
    """当前 Unix 毫秒时间戳。"""
    return int(now().timestamp() * 1000)


def add_days_iso(value: str | datetime | None, days: int) -> str | None:
    """在给定时间上加 N 天并返回 ISO 字符串（解析失败返回 None）。"""
    if value is None:
        return None
    base = value if isinstance(value, datetime) else parse_iso(str(value))
    if base is None:
        return None
    return to_iso(base + timedelta(days=int(days)))
