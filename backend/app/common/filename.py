"""文件名 / 目录名清洗（PRD 9.2 的 7 条规则）。

规则覆盖：
1. 非法字符 ``\\ / : * ? " < > |`` 与 ASCII 控制字符 0x00-0x1F → ``_``
2. 首尾空格与结尾 ``.`` 去除
3. 单段长度 ≤ 100 字符，超长截断 + ``_`` + 8 位内容哈希
4. Windows 保留名（CON/PRN/AUX/NUL/COM1-9/LPT1-9）前加 ``_``
5. 空名称 → ``untitled_{yyyyMMddHHmmss}``
6. 换行 / 连续空白合并为单个空格
7. 重名 → 本期由调用方覆盖并写 WARN（不在本模块内做版本化）
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Final

#: 单段名称最大长度
MAX_SEGMENT_LEN: Final[int] = 100

_ILLEGAL_RE: Final[re.Pattern[str]] = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

#: Windows 保留设备名
RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _hash8(text: str) -> str:
    """内容哈希前 8 位。"""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:8]


def sanitize(
    name: str | None,
    *,
    max_len: int = MAX_SEGMENT_LEN,
    default_prefix: str = "untitled",
) -> str:
    """清洗单个文件/目录名片段。

    Args:
        name: 原始名称（可为 None）。
        max_len: 单段最大长度（默认 100，含截断后缀）。
        default_prefix: 空名称时使用的前缀。

    Returns:
        可安全落盘的名称片段（不含路径分隔符）。
    """
    text = str(name or "")

    # 规则 6：换行 / 连续空白合并为单个空格
    text = _WHITESPACE_RE.sub(" ", text)
    # 规则 1：非法字符与控制字符替换
    text = _ILLEGAL_RE.sub("_", text)
    # 规则 2：去除首尾空格与点（Windows 不允许结尾点）
    text = text.strip(" .")

    # 规则 3：超长截断（保留 8 位哈希便于区分）
    if len(text) > max_len:
        keep = max(1, max_len - 9)
        text = f"{text[:keep]}_{_hash8(text)}"

    # 规则 5：空名称兜底
    if not text:
        text = f"{default_prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # 规则 4：保留名加前缀（按主名判断，扩展名不影响）
    stem = text.split(".", 1)[0].strip().upper()
    if stem in RESERVED_NAMES:
        text = f"_{text}"

    return text


def sanitize_ext(ext: str, default: str = "bin") -> str:
    """清洗扩展名（不含点，仅保留字母数字，最长 8 位）。"""
    text = re.sub(r"[^0-9a-zA-Z]", "", str(ext or "").strip().lstrip("."))
    return (text[:8] or default).lower()


def ensure_suffix(name: str, suffix: str) -> str:
    """确保名称以指定后缀结尾（suffix 可带点）。"""
    if not suffix:
        return name
    normalized = suffix if suffix.startswith(".") else f".{suffix}"
    return name if name.lower().endswith(normalized.lower()) else f"{name}{normalized}"


def strip_suffix(name: str) -> str:
    """去掉最后一个扩展名（产物展示名用）。"""
    text = str(name or "")
    head, dot, tail = text.rpartition(".")
    if dot and head and len(tail) <= 8:
        return head
    return text


def sanitize_relative(*parts: str, max_len: int = MAX_SEGMENT_LEN) -> str:
    """把多个片段清洗后用 ``/`` 拼接（仅用于展示，不做磁盘操作）。"""
    cleaned = [sanitize(part, max_len=max_len) for part in parts if part is not None]
    return "/".join(cleaned)
