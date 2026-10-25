"""图片集下载：单图失败不阻断同图集其他图片（失败项由调用方写 WARN 日志）。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from app.common.errors import BizError, PauseRequested
from app.common.logger import get_logger
from app.downloader.http_client import HttpClient

logger = get_logger(__name__)

#: 支持的图片扩展名
ALLOWED_EXTS: Final[frozenset[str]] = frozenset(
    {"jpg", "jpeg", "png", "webp", "gif", "bmp", "avif"}
)

_EXT_RE: Final[re.Pattern[str]] = re.compile(r"\.([0-9a-zA-Z]{2,5})(?:$|\?)")

#: 文件头魔数 → 扩展名
_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


@dataclass
class ImageSetResult:
    """图片集下载结果。"""

    out_dir: str
    count: int = 0
    failed: list[str] = field(default_factory=list)
    size: int = 0
    paused: bool = False


class ImageDownloader:
    """按列表顺序下载图集（序号 001 起，位宽 ≥3）。"""

    def __init__(self, http: HttpClient | None = None) -> None:
        self.http: HttpClient = http or HttpClient()

    def download_set(
        self,
        urls: list[str],
        out_dir: str,
        *,
        on_step: Callable[[int, int], None] | None = None,
        checkpoint: Callable[[], bool] | None = None,
    ) -> ImageSetResult:
        """下载整组图片。

        Args:
            urls: 图片地址列表（保持列表页原始顺序）。
            out_dir: 目标目录（已由 PathBuilder 创建）。
            on_step: 每张图完成后回调 ``(已完成, 总数)``。
            checkpoint: 每张图完成后调用，返回 False 表示暂停。

        Returns:
            ImageSetResult（含成功数、失败 URL、目录总大小）。
        """
        target_dir = Path(out_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        total = len(urls)
        width = max(3, len(str(max(total, 1))))
        result = ImageSetResult(out_dir=str(target_dir))

        for index, url in enumerate(urls, start=1):
            if checkpoint is not None and not checkpoint():
                result.paused = True
                logger.info("图片集下载已暂停：%s（%s/%s）", target_dir.name, index - 1, total)
                break
            try:
                written = self._download_one(url, target_dir, index, width)
            except BizError as exc:
                logger.warning("图片下载失败（%s/%s）%s：%s", index, total, url, exc.message)
                result.failed.append(url)
            except OSError as exc:
                logger.warning("图片写盘失败（%s/%s）%s：%s", index, total, url, exc)
                result.failed.append(url)
            else:
                result.count += 1
                result.size += written
            if on_step is not None:
                on_step(index, total)

        if result.paused:
            # 暂停不是错误：交由调度器把任务回退 pending
            raise PauseRequested("图片集下载已暂停")
        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _download_one(self, url: str, target_dir: Path, index: int, width: int) -> int:
        """下载单张图片：先写 ``.part`` 再原子替换。"""
        data = self.http.get_bytes(url, retries=0)
        if not data:
            raise BizError(ErrCode.HTTP_ERROR, "图片内容为空", retryable=True)
        ext = self._guess_ext(url, data)
        target = target_dir / f"{index:0{width}d}.{ext}"
        part = target.with_name(f"{target.name}.part")
        part.write_bytes(data)
        part.replace(target)
        return len(data)

    @staticmethod
    def _guess_ext(url: str, data: bytes) -> str:
        """推断图片扩展名：URL 后缀 → 文件头魔数 → 兜底 jpg。"""
        match = _EXT_RE.search(str(url).lower())
        if match and match.group(1) in ALLOWED_EXTS:
            return "jpg" if match.group(1) == "jpeg" else match.group(1)
        for magic, ext in _MAGIC:
            if data.startswith(magic):
                return ext
        return "jpg"
