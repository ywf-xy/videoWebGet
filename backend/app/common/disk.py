"""磁盘工具：剩余空间检查（<500MB 抛 4008）、可写性探测（返回 errno 原因）、目录大小统计。"""

from __future__ import annotations

import errno as errno_mod
import os
import shutil
import tempfile
from pathlib import Path

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger
from app.config import DEFAULTS

logger = get_logger(__name__)

MIN_FREE_MB: int = int(DEFAULTS["disk.min_free_mb"])


def existing_ancestor(path: str | Path) -> Path:
    """返回路径最近的已存在祖先目录（用于磁盘/空间探测）。"""
    target = Path(path).expanduser().resolve()
    for candidate in [target, *target.parents]:
        if candidate.exists():
            return candidate
    return Path(target.anchor or os.getcwd())


def free_bytes(path: str | Path) -> int:
    """目标路径所在磁盘的剩余字节数。"""
    try:
        return int(shutil.disk_usage(existing_ancestor(path)).free)
    except OSError:  # pragma: no cover - 极端环境
        return 0


def ensure_free_space(path: str | Path, min_free_mb: int | None = None) -> None:
    """剩余空间不足时抛出 ``4008 DISK_FULL``。"""
    threshold = MIN_FREE_MB if min_free_mb is None else int(min_free_mb)
    free_mb = free_bytes(path) / (1024 * 1024)
    if free_mb < threshold:
        raise BizError(
            ErrCode.DISK_FULL,
            f"磁盘空间不足：{Path(path)} 剩余 {free_mb:.0f}MB，低于 {threshold}MB 阈值",
            retryable=False,
        )


def check_writable(path: str | Path) -> tuple[bool, int | None, str | None]:
    """探测目录可写性。

    Returns:
        (是否可写, errno, 原因描述)
    """
    target = Path(path).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, exc.errno or errno_mod.EACCES, f"无法创建目录：{exc.strerror or exc}"
    try:
        with tempfile.NamedTemporaryFile(dir=str(target), prefix=".write_test_", delete=True):
            pass
    except OSError as exc:
        return False, exc.errno or errno_mod.EACCES, f"目录不可写：{exc.strerror or exc}"
    return True, None, None


def ensure_writable(path: str | Path) -> None:
    """目录不可写时抛出 ``5002 PATH_NOT_WRITABLE``。"""
    ok, code, reason = check_writable(path)
    if not ok:
        raise BizError(
            ErrCode.PATH_NOT_WRITABLE,
            f"输出目录不可写：{reason or path}",
            retryable=False,
            detail=f"errno={code}",
        )


def dir_size(path: str | Path) -> int:
    """递归统计目录内文件总字节数（文件则返回自身大小）。"""
    target = Path(path)
    if not target.exists():
        return 0
    if target.is_file():
        try:
            return target.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(target):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def safe_size(path: str | Path) -> int:
    """文件/目录大小的安全读取（异常返回 0）。"""
    try:
        return dir_size(path)
    except OSError:  # pragma: no cover
        return 0
