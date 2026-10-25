"""内容指纹：URL 规范化 + MD5 组合摘要（S3 去重、task_result.fingerprint 唯一来源）。

阶段一（策略计算）与阶段二（任务落盘）必须使用同一套指纹算法，
否则「历史成功记录命中」判定会失效。
"""

from __future__ import annotations

import hashlib
import re
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DEFAULT_PORTS: Final[dict[str, str]] = {"http": "80", "https": "443"}
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalize_url(url: str | None) -> str:
    """URL 规范化：小写 scheme/host、去默认端口、去 fragment、排序 query、去尾斜杠。"""
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port is not None and str(port) != _DEFAULT_PORTS.get(scheme, ""):
        netloc = f"{host}:{port}"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def md5_hex(text: str) -> str:
    """字符串 MD5 十六进制摘要。"""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def item_fingerprint(url: str | None, title: str | None = "") -> str:
    """条目指纹：规范化 URL + 标题（阶段一/阶段二共用）。"""
    normalized = normalize_url(url)
    clean_title = _WS_RE.sub(" ", str(title or "").strip())
    return md5_hex(f"{normalized}|{clean_title}")


def content_fingerprint(text: str | None) -> str:
    """正文内容指纹（P2 预留，图片集 / 章节正文可比对）。"""
    body = _WS_RE.sub(" ", str(text or "")).strip()
    return md5_hex(body)


def image_fingerprint(url: str | None, index: int = 0) -> str:
    """单图指纹：规范化图片 URL + 序号。"""
    return md5_hex(f"{normalize_url(url)}|{int(index)}")
