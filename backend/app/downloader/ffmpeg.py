"""ffmpeg / ffprobe 封装。

- ``detect()`` 解析 ``ffmpeg -version``，结果缓存；
- 缺失时 ``to_mp4`` 抛 ``3003 FFMPEG_MISSING``（不重试）；
- 转封装主路径 ``-c copy``，失败自动回退 ``libx264 + aac`` 重编码；
- ``probe_duration`` 优先 ffprobe，回退解析 ffmpeg stderr 的 ``Duration:``。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.common.errors import BizError, ErrCode
from app.common.logger import get_logger

logger = get_logger(__name__)

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"ffmpeg version\s+(\S+)", re.IGNORECASE)
_DURATION_RE: Final[re.Pattern[str]] = re.compile(
    r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", re.IGNORECASE
)
#: Windows 下隐藏子进程控制台窗口
_NO_WINDOW: Final[int] = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _local_tool_candidates() -> list[Path]:
    """项目内置 ffmpeg 解压目录的候选可执行文件位置。

    本文件位于 ``<项目根>/backend/app/downloader/ffmpeg.py``，因此 ``parents[3]`` 即项目根。
    优先查 ``tools/ffmpeg/bin``，其次 ``tools/ffmpeg`` 根，再次 ``tools/ffmpeg/ffmpeg``
    （兼容某些压缩包多套一层目录的解压结构）。
    """
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    base = Path(__file__).resolve().parents[3] / "tools" / "ffmpeg"
    return [
        base / "bin" / exe,
        base / exe,
        base / "ffmpeg" / exe,
    ]


@dataclass(frozen=True)
class FfmpegStatus:
    """ffmpeg 探测结果快照。"""

    available: bool = False
    version: str | None = None
    path: str | None = None


class FfmpegConverter:
    """ffmpeg 可执行文件封装（进程内单例使用）。"""

    #: 自测脚本可置为 True 以强制走「ffmpeg 缺失」兜底路径
    force_unavailable: bool = False

    def __init__(self, executable: str | None = None) -> None:
        self._lock = threading.Lock()
        self._executable: str | None = executable
        self._ffprobe: str | None = None
        self._version: str | None = None
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # 探测
    # ------------------------------------------------------------------
    def _run(self, args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        """执行子进程（捕获输出、隐藏窗口）。"""
        return subprocess.run(  # noqa: S603 - 本地可信命令
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
            check=False,
        )

    def _resolve_ffmpeg(self) -> str | None:
        """解析 ffmpeg 可执行文件：优先 PATH，其次项目内置 ``tools/ffmpeg`` 目录。"""
        if self._executable:
            return self._executable
        from_path = shutil.which("ffmpeg")
        if from_path:
            return from_path
        for cand in _local_tool_candidates():
            if cand.is_file():
                logger.info("使用项目内置 ffmpeg：%s", cand)
                return str(cand)
        return None

    def _resolve_ffprobe(self, ffmpeg_path: str) -> str | None:
        """解析 ffprobe：优先 PATH，其次 ffmpeg 同级目录下的 ``ffprobe(.exe)``。"""
        from_path = shutil.which("ffprobe")
        if from_path:
            return str(Path(from_path))
        exe = Path(ffmpeg_path)
        for name in ("ffprobe.exe", "ffprobe"):
            cand = exe.with_name(name)
            if cand.is_file():
                return str(cand)
        return None

    def detect(self, force: bool = False) -> bool:
        """探测 ffmpeg 是否可用（结果缓存，``force=True`` 强制重探）。"""
        with self._lock:
            if self._available is not None and not force:
                return self._available
            if self.force_unavailable:
                self._available = False
                self._version = None
                self._executable = None
                self._ffprobe = None
                logger.warning("ffmpeg 被显式置为不可用（自测/降级模式）")
                return False
            executable = self._resolve_ffmpeg()
            if not executable:
                self._available = False
                self._version = None
                self._executable = None
                logger.warning("未检测到 ffmpeg（PATH 与项目 tools 目录均未找到），视频任务将无法转为 MP4")
                return False
            try:
                result = self._run([executable, "-version"], timeout=10)
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("ffmpeg 探测失败：%s", exc)
                self._available = False
                return False
            if result.returncode != 0:
                logger.warning("ffmpeg 返回码异常：%s", result.returncode)
                self._available = False
                return False
            first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
            match = _VERSION_RE.search(first_line)
            self._version = match.group(1) if match else "unknown"
            self._executable = executable
            self._ffprobe = self._resolve_ffprobe(executable)
            self._available = True
            logger.info("检出 ffmpeg %s：%s", self._version, self._executable)
            return True

    @property
    def available(self) -> bool:
        """ffmpeg 是否可用（首次访问自动探测）。"""
        if self._available is None:
            return self.detect()
        return bool(self._available)

    @property
    def version(self) -> str | None:
        """ffmpeg 版本号。"""
        if self._available is None:
            self.detect()
        return self._version

    @property
    def path(self) -> str | None:
        """ffmpeg 可执行文件路径。"""
        if self._available is None:
            self.detect()
        return self._executable

    @property
    def ffprobe_path(self) -> str | None:
        """ffprobe 可执行文件路径。"""
        if self._available is None:
            self.detect()
        return self._ffprobe

    def status(self) -> FfmpegStatus:
        """返回探测结果快照。"""
        return FfmpegStatus(
            available=self.available, version=self.version, path=self.path
        )

    # ------------------------------------------------------------------
    # 转封装
    # ------------------------------------------------------------------
    def to_mp4(self, src: str | Path, dst: str | Path, *, reencode_fallback: bool = True) -> str:
        """把源文件转封装为 MP4（先 ``-c copy``，失败回退重编码）。

        Returns:
            目标文件绝对路径。

        Raises:
            BizError: ``3003`` ffmpeg 缺失 / ``4006`` 转换失败。
        """
        if not self.available or not self._executable:
            raise BizError(ErrCode.FFMPEG_MISSING, retryable=False)
        source = Path(src)
        if not source.exists() or source.stat().st_size <= 0:
            raise BizError(ErrCode.M3U8_PARSE, f"待转换文件不存在或为空：{source}", retryable=False)
        target = Path(dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(f"{target.stem}.part{target.suffix or '.mp4'}")

        copy_cmd = [
            self._executable,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-movflags",
            "+faststart",
            str(temp_target),
        ]
        result = self._run(copy_cmd, timeout=1800)
        if result.returncode != 0 or not temp_target.exists() or temp_target.stat().st_size == 0:
            logger.warning("ffmpeg -c copy 失败（%s），回退重编码", (result.stderr or "").strip()[:300])
            if not reencode_fallback:
                raise BizError(
                    ErrCode.M3U8_PARSE,
                    "ffmpeg 转封装失败",
                    retryable=False,
                    detail=(result.stderr or "").strip()[:500],
                )
            temp_target.unlink(missing_ok=True)
            reencode_cmd = [
                self._executable,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temp_target),
            ]
            result = self._run(reencode_cmd, timeout=7200)
            if result.returncode != 0 or not temp_target.exists() or temp_target.stat().st_size == 0:
                temp_target.unlink(missing_ok=True)
                raise BizError(
                    ErrCode.M3U8_PARSE,
                    "ffmpeg 转换 MP4 失败",
                    retryable=False,
                    detail=(result.stderr or "").strip()[:500],
                )
        temp_target.replace(target)
        return str(target)

    def probe_duration(self, path: str | Path) -> float:
        """探测媒体时长（秒），失败返回 0.0。"""
        target = Path(path)
        if not target.exists():
            return 0.0
        ffprobe = self.ffprobe_path
        if ffprobe:
            try:
                result = self._run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(target),
                    ],
                    timeout=60,
                )
                text = (result.stdout or "").strip()
                if text:
                    return float(text.splitlines()[0])
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        if not self.available or not self._executable:
            return 0.0
        try:
            result = self._run([self._executable, "-i", str(target)], timeout=60)
        except (OSError, subprocess.SubprocessError):
            return 0.0
        match = _DURATION_RE.search(f"{result.stdout}\n{result.stderr}")
        if not match:
            return 0.0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


_ffmpeg_singleton: FfmpegConverter | None = None


def get_ffmpeg() -> FfmpegConverter:
    """获取进程级 ffmpeg 封装单例。"""
    global _ffmpeg_singleton
    if _ffmpeg_singleton is None:
        _ffmpeg_singleton = FfmpegConverter()
    return _ffmpeg_singleton


def ffmpeg_info() -> dict[str, object]:
    """供 ``/api/system/info`` 使用的探测结果。"""
    status = get_ffmpeg().status()
    return {"available": status.available, "version": status.version, "path": status.path}
