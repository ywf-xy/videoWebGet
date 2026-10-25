"""m3u8 播放列表解析（RFC 8216 子集）。

支持：
- master playlist → 选最高 BANDWIDTH 的 variant；
- media playlist → 分片列表（EXTINF 时长、EXT-X-MEDIA-SEQUENCE、EXT-X-KEY）；
- 加密判定：``METHOD=NONE`` / ``AES-128`` 支持；``SAMPLE-AES`` / DRM（Widevine、
  FairPlay、PlayReady）抛 ``4007 DRM_UNSUPPORTED``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urljoin

from app.common.errors import BizError, ErrCode

#: DRM 相关 KEYFORMAT 关键字
_DRM_KEYFORMATS: Final[tuple[str, ...]] = (
    "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",  # Widevine
    "com.apple.streamingkeydelivery",  # FairPlay
    "com.microsoft.playready",
    "urn:mpeg:dash",
)
_UNSUPPORTED_METHODS: Final[frozenset[str]] = frozenset({"SAMPLE-AES", "SAMPLE-AES-CTR"})


@dataclass(frozen=True)
class KeyInfo:
    """EXT-X-KEY 描述。"""

    method: str
    uri: str = ""
    iv: bytes | None = None
    keyformat: str | None = None


@dataclass(frozen=True)
class Segment:
    """单个分片。"""

    index: int
    uri: str
    duration: float = 0.0
    sequence: int = 0


@dataclass
class MediaPlaylist:
    """media playlist 解析结果。"""

    segments: list[Segment] = field(default_factory=list)
    media_sequence: int = 0
    target_duration: float = 0.0
    keys: dict[int, KeyInfo] = field(default_factory=dict)
    encryption_method: str | None = None

    @property
    def total_duration(self) -> float:
        """分片时长合计（秒）。"""
        return sum(seg.duration for seg in self.segments)

    @property
    def is_encrypted(self) -> bool:
        """是否存在加密分片。"""
        return self.encryption_method == "AES-128"


class M3U8Parser:
    """m3u8 文本解析器（纯函数，无 IO）。"""

    @staticmethod
    def is_master(content: str) -> bool:
        """判断是否为 master playlist。"""
        return "#EXT-X-STREAM-INF" in (content or "")

    def parse_master(self, content: str, base_url: str = "") -> str:
        """从 master playlist 中选出最高带宽 variant 的绝对地址。

        Returns:
            variant 的绝对 URL；非 master 或未找到时返回空字符串。
        """
        lines = [line.strip() for line in (content or "").splitlines()]
        best_bandwidth = -1
        best_uri = ""
        for index, line in enumerate(lines):
            if not line.upper().startswith("#EXT-X-STREAM-INF"):
                continue
            bandwidth = self._attr_int(line, "BANDWIDTH", 0)
            uri = self._next_uri(lines, index + 1)
            if not uri:
                continue
            if bandwidth > best_bandwidth:
                best_bandwidth = bandwidth
                best_uri = uri
        if not best_uri:
            return ""
        return urljoin(base_url, best_uri) if base_url else best_uri

    def parse_media(self, content: str, base_url: str = "") -> MediaPlaylist:
        """解析 media playlist。

        Raises:
            BizError: ``4006`` 无有效分片 / ``4007`` 加密方式不支持。
        """
        text = content or ""
        if self.is_master(text):
            raise BizError(ErrCode.M3U8_PARSE, "传入的是 master playlist，需先选择 variant")

        playlist = MediaPlaylist()
        lines = [line.strip() for line in text.splitlines()]
        current_duration = 0.0
        current_key: KeyInfo | None = None
        index = 0
        for line in lines:
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                playlist.media_sequence = self._safe_int(line.split(":", 1)[1], 0)
            elif upper.startswith("#EXT-X-TARGETDURATION:"):
                playlist.target_duration = self._safe_float(line.split(":", 1)[1], 0.0)
            elif upper.startswith("#EXT-X-KEY:"):
                current_key = self._parse_key(line, base_url)
                if current_key.method == "AES-128":
                    playlist.encryption_method = "AES-128"
            elif upper.startswith("#EXTINF:"):
                current_duration = self._safe_float(line.split(":", 1)[1].split(",")[0], 0.0)
            elif line.startswith("#"):
                continue
            else:
                uri = urljoin(base_url, line) if base_url else line
                sequence = playlist.media_sequence + index
                playlist.segments.append(
                    Segment(
                        index=index,
                        uri=uri,
                        duration=current_duration,
                        sequence=sequence,
                    )
                )
                if current_key is not None and current_key.method == "AES-128":
                    playlist.keys[index] = current_key
                index += 1
                current_duration = 0.0

        if not playlist.segments:
            raise BizError(ErrCode.M3U8_PARSE, "m3u8 中没有可用分片")
        return playlist

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _parse_key(self, line: str, base_url: str) -> KeyInfo:
        """解析 EXT-X-KEY 行，DRM/SAMPLE-AES 直接抛 4007。"""
        attrs = self._parse_attrs(line.split(":", 1)[1] if ":" in line else "")
        method = str(attrs.get("METHOD", "NONE")).upper()
        keyformat = attrs.get("KEYFORMAT")
        uri = attrs.get("URI", "")
        iv_raw = attrs.get("IV")

        if method == "NONE":
            return KeyInfo(method="NONE")
        if method in _UNSUPPORTED_METHODS:
            raise BizError(
                ErrCode.DRM_UNSUPPORTED,
                f"该视频使用 {method} 加密，暂不支持下载",
                retryable=False,
                detail=f"method={method}",
            )
        if method != "AES-128":
            raise BizError(
                ErrCode.DRM_UNSUPPORTED,
                f"不支持的加密方式：{method}",
                retryable=False,
                detail=f"method={method}",
            )
        if keyformat:
            lowered = keyformat.lower()
            for drm in _DRM_KEYFORMATS:
                if drm in lowered:
                    raise BizError(
                        ErrCode.DRM_UNSUPPORTED,
                        "该视频使用 DRM 加密，暂不支持下载",
                        retryable=False,
                        detail=f"keyformat={keyformat}",
                    )
            if "identity" not in lowered and "aes-128" not in lowered:
                raise BizError(
                    ErrCode.DRM_UNSUPPORTED,
                    f"不支持的密钥格式：{keyformat}",
                    retryable=False,
                    detail=f"keyformat={keyformat}",
                )
        if not uri:
            raise BizError(ErrCode.M3U8_PARSE, "EXT-X-KEY 缺少密钥地址 URI")

        iv: bytes | None = None
        if iv_raw:
            hex_text = iv_raw[2:] if iv_raw.lower().startswith("0x") else iv_raw
            try:
                iv = bytes.fromhex(hex_text)
            except ValueError as exc:
                raise BizError(ErrCode.M3U8_PARSE, "EXT-X-KEY 的 IV 不是合法十六进制") from exc
            if len(iv) != 16:
                raise BizError(ErrCode.M3U8_PARSE, "EXT-X-KEY 的 IV 长度必须为 16 字节")
        return KeyInfo(
            method=method,
            uri=urljoin(base_url, uri) if base_url else uri,
            iv=iv,
            keyformat=keyformat,
        )

    @staticmethod
    def _parse_attrs(text: str) -> dict[str, str]:
        """解析 ``KEY=VALUE,KEY="VALUE"`` 形式的属性串。"""
        attrs: dict[str, str] = {}
        buffer = ""
        in_quotes = False
        items: list[str] = []
        for char in text:
            if char == '"':
                in_quotes = not in_quotes
                buffer += char
            elif char == "," and not in_quotes:
                items.append(buffer)
                buffer = ""
            else:
                buffer += char
        if buffer:
            items.append(buffer)
        for item in items:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            attrs[key.strip().upper()] = value.strip().strip('"')
        return attrs

    def _attr_int(self, line: str, name: str, default: int) -> int:
        """从标签行取整型属性。"""
        attrs = self._parse_attrs(line.split(":", 1)[1] if ":" in line else "")
        return self._safe_int(attrs.get(name, ""), default)

    @staticmethod
    def _safe_int(text: str, default: int) -> int:
        try:
            return int(str(text).strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(text: str, default: float) -> float:
        try:
            return float(str(text).strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _next_uri(lines: list[str], start: int) -> str:
        """取 ``start`` 之后的第一条非注释行（URI）。"""
        for line in lines[start:]:
            if not line or line.startswith("#"):
                continue
            return line
        return ""


def default_iv(sequence: int) -> bytes:
    """缺省 IV：媒体序号的 16 字节大端表示（RFC 8216 §5.2）。"""
    return int(max(0, sequence)).to_bytes(16, "big")
