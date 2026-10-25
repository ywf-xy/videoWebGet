"""m3u8 分片下载 + 解密 + 合并 + 转 MP4。

路径策略（ARCHITECTURE §6.2）：
1. 拉取 playlist（master → 最高带宽 variant）；
2. ``EXT-X-KEY`` 为 AES-128 时拉取密钥，逐片 AES-128-CBC 解密；
   ``SAMPLE-AES`` / DRM 由解析层抛 ``4007``；
3. 并发下载分片（≤ ``min(4, max_threads)``，单片失败重试 2 次）到 ``{root}/.tmp/{task_id}/``；
4. 按 EXTINF 顺序二进制 concat 成 ``merged.ts``；
5. ffmpeg 可用 → 转封装 MP4；不可用 → 保留可播放 ``.ts`` 并抛 ``DegradedArtifactError``
   （任务按 PRD P0-10④ 标 failed，产物仍登记，装好 ffmpeg 后重试可复用分片）。

AES 实现：优先 pycryptodome，缺失时用内置纯 Python AES-128-CBC（无外部依赖）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.common.errors import BizError, ErrCode, PauseRequested
from app.common.logger import get_logger
from app.config import DEFAULTS
from app.downloader.ffmpeg import FfmpegConverter, get_ffmpeg
from app.downloader.http_client import HttpClient
from app.parsers.m3u8_parser import (
    KeyInfo,
    M3U8Parser,
    MediaPlaylist,
    Segment,
    default_iv,
)

logger = get_logger(__name__)

#: 单分片额外重试次数（PRD 9.7）
SEGMENT_RETRIES: Final[int] = 2

try:  # pragma: no cover - 依赖可选
    from Crypto.Cipher import AES as _CryptoAES  # type: ignore

    _HAS_PYCRYPTODOME = True
except Exception:  # noqa: BLE001 - 缺依赖时走纯 Python 实现
    _CryptoAES = None  # type: ignore[assignment]
    _HAS_PYCRYPTODOME = False


# ---------------------------------------------------------------------------
# AES-128-CBC 解密（pycryptodome 优先，纯 Python 兜底）
# ---------------------------------------------------------------------------
def _xtime(value: int) -> int:
    value &= 0xFF
    return ((value << 1) ^ 0x1B) & 0xFF if value & 0x80 else (value << 1) & 0xFF


def _gmul(left: int, right: int) -> int:
    """GF(2^8) 乘法。"""
    result = 0
    left &= 0xFF
    right &= 0xFF
    while right:
        if right & 1:
            result ^= left
        left = _xtime(left)
        right >>= 1
    return result & 0xFF


def _build_sbox() -> list[int]:
    """由 GF(2^8) 乘法逆元 + 仿射变换生成 AES S 盒（避免硬编码 256 项）。"""
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        p &= 0xFF
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        q &= 0xFF
        x = (
            q
            ^ ((q << 1) | (q >> 7))
            ^ ((q << 2) | (q >> 6))
            ^ ((q << 3) | (q >> 5))
            ^ ((q << 4) | (q >> 4))
        )
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX: Final[list[int]] = _build_sbox()
_INV_SBOX: Final[list[int]] = [0] * 256
for _index, _value in enumerate(_SBOX):
    _INV_SBOX[_value] = _index

_RCON: Final[list[int]] = [0x01]
for _ in range(9):
    _RCON.append(_xtime(_RCON[-1]))


def _expand_key(key: bytes) -> list[list[int]]:
    """AES-128 密钥扩展 → 11 组轮密钥。"""
    words = [list(key[i : i + 4]) for i in range(0, 16, 4)]
    for index in range(4, 44):
        temp = list(words[index - 1])
        if index % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[byte] for byte in temp]
            temp[0] ^= _RCON[index // 4 - 1]
        words.append([words[index - 4][j] ^ temp[j] for j in range(4)])
    return [sum(words[4 * round_no : 4 * round_no + 4], []) for round_no in range(11)]


def _inv_shift_rows(state: list[int]) -> list[int]:
    out = [0] * 16
    for column in range(4):
        for row in range(4):
            out[row + 4 * column] = state[row + 4 * ((column - row) % 4)]
    return out


def _inv_mix_columns(state: list[int]) -> list[int]:
    out = [0] * 16
    for column in range(4):
        block = state[4 * column : 4 * column + 4]
        out[4 * column + 0] = (
            _gmul(block[0], 14) ^ _gmul(block[1], 11) ^ _gmul(block[2], 13) ^ _gmul(block[3], 9)
        )
        out[4 * column + 1] = (
            _gmul(block[0], 9) ^ _gmul(block[1], 14) ^ _gmul(block[2], 11) ^ _gmul(block[3], 13)
        )
        out[4 * column + 2] = (
            _gmul(block[0], 13) ^ _gmul(block[1], 9) ^ _gmul(block[2], 14) ^ _gmul(block[3], 11)
        )
        out[4 * column + 3] = (
            _gmul(block[0], 11) ^ _gmul(block[1], 13) ^ _gmul(block[2], 9) ^ _gmul(block[3], 14)
        )
    return out


def _decrypt_block(block: bytes, round_keys: list[list[int]]) -> list[int]:
    state = [byte ^ key for byte, key in zip(block, round_keys[10])]
    for round_no in range(9, 0, -1):
        state = _inv_shift_rows(state)
        state = [_INV_SBOX[byte] for byte in state]
        state = [byte ^ key for byte, key in zip(state, round_keys[round_no])]
        state = _inv_mix_columns(state)
    state = _inv_shift_rows(state)
    state = [_INV_SBOX[byte] for byte in state]
    return [byte ^ key for byte, key in zip(state, round_keys[0])]


def _pure_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """纯 Python AES-128-CBC 解密（忽略尾部不足 16 字节的残块）。"""
    round_keys = _expand_key(key)
    out = bytearray()
    previous = iv
    usable = len(data) - len(data) % 16
    for offset in range(0, usable, 16):
        block = data[offset : offset + 16]
        plain = bytes(_decrypt_block(block, round_keys))
        out += bytes(a ^ b for a, b in zip(plain, previous))
        previous = block
    return bytes(out)


def _strip_pkcs7(data: bytes) -> bytes:
    """去除 PKCS#7 填充（非法填充时原样返回）。"""
    if not data:
        return data
    padding = data[-1]
    if 1 <= padding <= 16 and len(data) >= padding and data[-padding:] == bytes([padding]) * padding:
        return data[:-padding]
    return data


def aes128_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC 解密 + 去 PKCS#7 填充。"""
    if len(key) != 16 or len(iv) != 16:
        raise BizError(ErrCode.M3U8_PARSE, "AES 密钥或 IV 长度不是 16 字节", retryable=False)
    if _HAS_PYCRYPTODOME and _CryptoAES is not None:  # pragma: no cover - 依赖可选
        cipher = _CryptoAES.new(key, _CryptoAES.MODE_CBC, iv)
        decrypted = cipher.decrypt(data[: len(data) - len(data) % 16])
    else:
        decrypted = _pure_cbc_decrypt(data, key, iv)
    return _strip_pkcs7(decrypted)


# ---------------------------------------------------------------------------
# 下载结果
# ---------------------------------------------------------------------------
@dataclass
class DownloadResult:
    """单次 m3u8 下载结果。"""

    path: str
    size: int
    duration_s: float
    segment_count: int
    degraded: bool = False


class DegradedArtifactError(BizError):
    """ffmpeg 缺失导致的降级产物异常（携带已产出的 ``.ts`` 路径，便于登记产物）。"""

    def __init__(self, artifact_path: str, file_size: int, message: str | None = None) -> None:
        super().__init__(ErrCode.FFMPEG_MISSING, message, retryable=False)
        self.artifact_path: str = artifact_path
        self.file_size: int = int(file_size)


class M3U8Downloader:
    """HLS 下载器：分片并发 + AES-128 解密 + concat + ffmpeg 转封装。"""

    def __init__(
        self,
        http: HttpClient | None = None,
        max_segment_workers: int | None = None,
        converter: FfmpegConverter | None = None,
    ) -> None:
        self.http: HttpClient = http or HttpClient()
        workers = int(DEFAULTS["segment.concurrency"] if max_segment_workers is None else max_segment_workers)
        self.max_segment_workers: int = max(1, min(workers, int(DEFAULTS["segment.concurrency"])))
        self.converter: FfmpegConverter = converter or get_ffmpeg()
        self.parser = M3U8Parser()

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def download(
        self,
        m3u8_url: str,
        task_id: int,
        work_dir: str,
        *,
        output_path: str | None = None,
        ts_fallback_path: str | None = None,
        checkpoint: Callable[[], bool] | None = None,
        on_step: Callable[[int, int], None] | None = None,
    ) -> DownloadResult:
        """下载并产出 MP4。

        Args:
            m3u8_url: 播放列表地址。
            task_id: 任务 ID（仅用于日志与临时目录）。
            work_dir: 任务临时目录。
            output_path: MP4 目标路径；为 None 时仅返回临时 merged.ts。
            ts_fallback_path: ffmpeg 缺失时 ``.ts`` 的落盘路径。
            checkpoint: 每个原子步骤后调用，返回 False 表示需暂停（抛 PauseRequested）。
            on_step: 分片完成回调 ``(已完成, 总数)``。

        Raises:
            BizError: 4006 解析失败 / 4007 DRM / 3003 ffmpeg 缺失（DegradedArtifactError）。
            PauseRequested: 用户暂停。
        """
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)
        merged = work / "merged.ts"

        def _check() -> None:
            if checkpoint is not None and not checkpoint():
                raise PauseRequested()

        if not (merged.exists() and merged.stat().st_size > 0):
            playlist = self._load_playlist(m3u8_url)
            logger.info(
                "任务 %s：m3u8 分片 %s 个，加密=%s",
                task_id,
                len(playlist.segments),
                playlist.encryption_method or "none",
            )
            key_cache = self._load_keys(playlist)
            self._download_segments(
                playlist=playlist,
                key_cache=key_cache,
                work=work,
                checkpoint=_check,
                on_step=on_step,
                task_id=task_id,
            )
            _check()
            self._concat(playlist, work, merged)
        else:
            logger.info("任务 %s：复用已合并的 merged.ts（断点续传）", task_id)

        _check()
        size = merged.stat().st_size
        if size <= 0:
            raise BizError(ErrCode.M3U8_PARSE, "合并后的分片文件为空", retryable=True)

        # ffmpeg 缺失 → 保留可播放 .ts 并登记产物后按 3003 失败
        if not self.converter.available:
            fallback = Path(ts_fallback_path) if ts_fallback_path else merged
            fallback.parent.mkdir(parents=True, exist_ok=True)
            if fallback.resolve() != merged.resolve():
                fallback.write_bytes(merged.read_bytes())
            raise DegradedArtifactError(str(fallback), fallback.stat().st_size)

        if output_path is None:
            return DownloadResult(
                path=str(merged),
                size=size,
                duration_s=self.converter.probe_duration(merged),
                segment_count=len(list(work.glob("seg_*.ts"))),
            )

        _check()
        mp4_path = self.converter.to_mp4(merged, output_path)
        duration = self.converter.probe_duration(mp4_path)
        final_size = Path(mp4_path).stat().st_size
        return DownloadResult(
            path=mp4_path,
            size=final_size,
            duration_s=duration,
            segment_count=len(list(work.glob("seg_*.ts"))),
        )

    # ------------------------------------------------------------------
    # playlist
    # ------------------------------------------------------------------
    def _load_playlist(self, m3u8_url: str) -> MediaPlaylist:
        """拉取 playlist（master 自动选最高带宽 variant）。"""
        content = self.http.get_text(m3u8_url)
        if self.parser.is_master(content):
            variant = self.parser.parse_master(content, m3u8_url)
            if not variant:
                raise BizError(ErrCode.M3U8_PARSE, "master playlist 中没有可用码率分支", retryable=True)
            logger.info("master playlist 选择 variant：%s", variant)
            content = self.http.get_text(variant)
            return self.parser.parse_media(content, variant)
        return self.parser.parse_media(content, m3u8_url)

    def _load_keys(self, playlist: MediaPlaylist) -> dict[str, bytes]:
        """拉取并缓存所有 AES-128 密钥。"""
        cache: dict[str, bytes] = {}
        for key_info in playlist.keys.values():
            if key_info.method != "AES-128" or not key_info.uri:
                continue
            if key_info.uri in cache:
                continue
            key_bytes = self.http.get_bytes(key_info.uri, retries=1)
            if len(key_bytes) != 16:
                raise BizError(
                    ErrCode.M3U8_PARSE,
                    f"AES 密钥长度异常（{len(key_bytes)} 字节，应为 16）",
                    retryable=False,
                )
            cache[key_info.uri] = key_bytes
        return cache

    # ------------------------------------------------------------------
    # 分片
    # ------------------------------------------------------------------
    def _download_segments(
        self,
        *,
        playlist: MediaPlaylist,
        key_cache: dict[str, bytes],
        work: Path,
        checkpoint: Callable[[], None],
        on_step: Callable[[int, int], None] | None,
        task_id: int,
    ) -> None:
        """并发下载全部分片，单片失败重试 2 次。"""
        total = len(playlist.segments)
        workers = max(1, min(self.max_segment_workers, total))
        done_counter = {"done": 0}
        lock = threading.Lock()

        def _one(segment: Segment) -> None:
            checkpoint()
            target = work / f"seg_{segment.index:05d}.ts"
            if target.exists() and target.stat().st_size > 0:
                with lock:
                    done_counter["done"] += 1
                    current = done_counter["done"]
                if on_step is not None:
                    on_step(current, total)
                return
            data = self._fetch_segment(segment)
            key_info: KeyInfo | None = playlist.keys.get(segment.index)
            if key_info is not None and key_info.method == "AES-128":
                key_bytes = key_cache.get(key_info.uri, b"")
                iv = key_info.iv or default_iv(segment.sequence)
                data = aes128_cbc_decrypt(data, key_bytes, iv)
            part = target.with_suffix(".part")
            part.write_bytes(data)
            part.replace(target)
            with lock:
                done_counter["done"] += 1
                current = done_counter["done"]
            if on_step is not None:
                on_step(current, total)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"seg{task_id}") as pool:
            futures = {pool.submit(_one, segment): segment for segment in playlist.segments}
            errors: list[BizError] = []
            for future in as_completed(futures):
                try:
                    future.result()
                except PauseRequested:
                    for pending in futures:
                        pending.cancel()
                    raise
                except BizError as exc:
                    errors.append(exc)
                except OSError as exc:
                    errors.append(BizError(ErrCode.INTERNAL, f"分片写盘失败：{exc}", retryable=True))
            if errors:
                # 全部失败视为流不可用；部分失败同样视为失败（保证产物完整）
                raise BizError(
                    ErrCode.HTTP_ERROR,
                    f"分片下载失败 {len(errors)} 个（首个：{errors[0].message}）",
                    retryable=True,
                )

    def _fetch_segment(self, segment: Segment) -> bytes:
        """下载单个分片（额外重试 SEGMENT_RETRIES 次）。"""
        last_error: BizError | None = None
        for attempt in range(SEGMENT_RETRIES + 1):
            try:
                return self.http.get_bytes(segment.uri, retries=0)
            except BizError as exc:
                last_error = exc
                if not exc.retryable:
                    raise
                if attempt < SEGMENT_RETRIES:
                    logger.warning(
                        "分片 %s 下载失败（第 %s 次重试）：%s",
                        segment.index,
                        attempt + 1,
                        exc.message,
                    )
        raise last_error or BizError(
            ErrCode.HTTP_ERROR, f"分片下载失败：{segment.uri}", retryable=True
        )

    # ------------------------------------------------------------------
    # 合并
    # ------------------------------------------------------------------
    def _concat(self, playlist: MediaPlaylist, work: Path, merged: Path) -> None:
        """按 EXTINF 顺序二进制拼接分片（不转码以保证速度）。"""
        part = merged.with_suffix(".part")
        with part.open("wb") as output:
            for segment in playlist.segments:
                segment_file = work / f"seg_{segment.index:05d}.ts"
                if not segment_file.exists():
                    raise BizError(
                        ErrCode.M3U8_PARSE,
                        f"分片文件缺失：{segment_file.name}",
                        retryable=True,
                    )
                with segment_file.open("rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
        part.replace(merged)
