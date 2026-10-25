"""日志：控制台 + ``logs/app.log``（5MB × 3 滚动），统一格式（ARCHITECTURE §11.4）。"""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
MAX_BYTES: Final[int] = 5 * 1024 * 1024
BACKUP_COUNT: Final[int] = 3
TRACEBACK_LIMIT: Final[int] = 4096

_configured: bool = False


def setup_logging(log_dir: str | Path, level: int = logging.INFO) -> None:
    """初始化根日志器（幂等）：控制台 + 滚动文件。"""
    global _configured
    if _configured:
        return

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        filename=directory / "app.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # uvicorn 默认日志器复用根处理器格式
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器。"""
    return logging.getLogger(name)


def format_exc(exc: BaseException | None = None, limit: int = TRACEBACK_LIMIT) -> str:
    """把异常格式化为截断的 traceback 摘要（≤4KB，落 task_log.ERROR 用）。"""
    if exc is None:
        text = traceback.format_exc()
    else:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 20] + "\n... (traceback 已截断)"
    return text


def error_message(code: int, message: str, detail: str = "") -> str:
    """``[错误码] 人话描述 | detail=...`` 的 task_log.ERROR 正文格式。"""
    parts = [f"[{code}] {message}"]
    if detail:
        parts.append(f"detail={detail}")
    return " | ".join(parts)
