"""落盘路径构建（PRD 9.1 目录规则 + 文件名清洗接入）。

四种模板（唯一定义处 ``TEMPLATES``）：
- 视频：``{root}/{数据源}/{分类}/{名称}.mp4``
- 文字-小说：``{root}/{数据源}/{分类}/{小说名}/{章节名}.{txt|pdf}``
- 文字-非小说：``{root}/{数据源}/{分类}/{yyyy-MM-dd}/{文章名}.{txt|pdf}``
- 图片：``{root}/{数据源}/{分类}/{yyyy-MM-dd}/{图集名}/{序号}.{ext}``

补充规则：分类空 → ``未分类``；目录缺失逐级创建；图片序号从 001 起且位宽 ≥3；
日期取任务执行日（本地时区），非条目发布日期。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Final, Protocol

from app.common.filename import sanitize, sanitize_ext
from app.common.logger import get_logger
from app.common.timeutil import today_str
from app.config import DEFAULTS

logger = get_logger(__name__)

#: 目录模板（唯一定义处，改规则只改这里）
TEMPLATES: Final[dict[str, str]] = {
    "video": "{root}/{ds}/{category}/{name}.mp4",
    "text_novel": "{root}/{ds}/{category}/{book}/{chapter}.{fmt}",
    "text_article": "{root}/{ds}/{category}/{date}/{title}.{fmt}",
    "image": "{root}/{ds}/{category}/{date}/{name}/{index}.{ext}",
}

#: 分类为空时的兜底目录名
UNCATEGORIZED: Final[str] = "未分类"

#: 小说名缺失时的兜底目录名
UNKNOWN_BOOK: Final[str] = "未命名作品"

#: 临时目录名
TEMP_DIRNAME: Final[str] = ".tmp"

#: Windows 路径长度预警阈值（MAX_PATH=260）
MAX_PATH_WARN: Final[int] = 240

#: 视频容器扩展名
VIDEO_EXT: Final[str] = "mp4"


class SourceLike(Protocol):
    """PathBuilder 需要的数据源最小接口（避免 common 层依赖 ORM 模型）。"""

    name: str
    category: str | None
    is_novel: int | bool


def _category_of(ds: SourceLike) -> str:
    """分类目录名（空 → 未分类）。"""
    raw = getattr(ds, "category", None)
    text = str(raw).strip() if raw is not None else ""
    return sanitize(text) if text else UNCATEGORIZED


class PathBuilder:
    """按规则生成产物路径，并负责目录创建与临时目录清理。"""

    def __init__(self, root: str | Path) -> None:
        self.root: str = str(Path(root).expanduser().resolve())

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _join(self, *parts: str) -> str:
        """拼接路径、创建父目录、做超长路径预警。"""
        path = os.path.join(self.root, *[p for p in parts if p])
        normalized = os.path.normpath(path)
        if len(normalized) > MAX_PATH_WARN:
            logger.warning("路径长度 %s 超过 %s，可能触发 Windows 路径限制：%s", len(normalized), MAX_PATH_WARN, normalized)
        parent = os.path.dirname(normalized)
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        return normalized

    @staticmethod
    def _ensure_dir(path: str) -> str:
        """创建目录（mkdir -p 语义）。"""
        Path(path).mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # 视频
    # ------------------------------------------------------------------
    def build_video(self, ds: SourceLike, name: str) -> str:
        """视频产物路径：``{root}/{ds}/{category}/{name}.mp4``。"""
        return self._join(
            sanitize(ds.name),
            _category_of(ds),
            f"{sanitize(name)}.{VIDEO_EXT}",
        )

    def build_video_ts(self, ds: SourceLike, name: str) -> str:
        """ffmpeg 缺失时的兜底产物路径（``.ts``，可直接播放）。"""
        return self._join(
            sanitize(ds.name),
            _category_of(ds),
            f"{sanitize(name)}.ts",
        )

    # ------------------------------------------------------------------
    # 文字
    # ------------------------------------------------------------------
    def build_text(
        self,
        ds: SourceLike,
        title: str,
        chapter: str = "",
        fmt: str = "txt",
        *,
        is_novel: bool | None = None,
        book: str | None = None,
        when: str | None = None,
    ) -> str:
        """文字产物路径。

        Args:
            ds: 数据源（需 name / category / is_novel）。
            title: 小说名（小说类）或文章名（非小说类）。
            chapter: 章节名（小说类必填，非小说类忽略）。
            fmt: ``txt`` / ``pdf``。
            is_novel: 覆盖数据源的 is_novel 判定。
            book: 小说名（小说类时优先于 title）。
            when: 任务执行日 yyyy-MM-dd，缺省取今天。
        """
        novel = bool(ds.is_novel) if is_novel is None else bool(is_novel)
        suffix = sanitize_ext(fmt, default="txt")
        if novel:
            book_name = sanitize(book or title or UNKNOWN_BOOK)
            chapter_name = sanitize(chapter or title or "正文")
            return self._join(
                sanitize(ds.name),
                _category_of(ds),
                book_name,
                f"{chapter_name}.{suffix}",
            )
        return self._join(
            sanitize(ds.name),
            _category_of(ds),
            sanitize(when or today_str()),
            f"{sanitize(title)}.{suffix}",
        )

    # ------------------------------------------------------------------
    # 图片
    # ------------------------------------------------------------------
    def build_image_dir(self, ds: SourceLike, name: str, when: str | None = None) -> str:
        """图片集目录：``{root}/{ds}/{category}/{yyyy-MM-dd}/{name}/``。"""
        path = self._join(
            sanitize(ds.name),
            _category_of(ds),
            sanitize(when or today_str()),
            sanitize(name),
        )
        return self._ensure_dir(path)

    def build_image_path(
        self,
        ds: SourceLike,
        name: str,
        index: int,
        total: int,
        ext: str = "jpg",
        when: str | None = None,
    ) -> str:
        """单图路径：序号宽度 = max(3, 总数位宽)，从 001 起。"""
        width = max(3, len(str(max(int(total), 1))))
        filename = f"{int(index):0{width}d}.{sanitize_ext(ext, default='jpg')}"
        return os.path.join(self.build_image_dir(ds, name, when), filename)

    # ------------------------------------------------------------------
    # 临时目录
    # ------------------------------------------------------------------
    def temp_dir(self, task_id: int) -> str:
        """任务级临时目录 ``{root}/.tmp/{task_id}/``。"""
        path = os.path.join(self.root, TEMP_DIRNAME, str(int(task_id)))
        return self._ensure_dir(path)

    def cleanup_temp(self, task_id: int) -> None:
        """清理任务临时目录（失败仅告警，不阻断主流程）。"""
        path = os.path.join(self.root, TEMP_DIRNAME, str(int(task_id)))
        shutil.rmtree(path, ignore_errors=True)

    def cleanup_stale_temp(self, ttl_hours: int | None = None) -> int:
        """清理超过 TTL 的临时目录（失败保留便于排查），返回清理数量。"""
        hours = int(DEFAULTS["temp.ttl_hours"] if ttl_hours is None else ttl_hours)
        deadline = time.time() - hours * 3600
        base = Path(self.root) / TEMP_DIRNAME
        if not base.exists():
            return 0
        removed = 0
        for child in base.iterdir():
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime < deadline:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            except OSError:  # pragma: no cover
                continue
        if removed:
            logger.info("清理过期临时目录 %s 个（TTL=%sh）", removed, hours)
        return removed
