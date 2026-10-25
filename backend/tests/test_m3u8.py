"""m3u8 解析（EXTINF / EXT-X-KEY / DRM 拒绝 / URI 拼接）+ AES-128-CBC 加解密往返。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from app.common.errors import BizError, ErrCode
from app.downloader import m3u8_downloader as downloader_module
from app.downloader.http_client import HttpClient
from app.downloader.m3u8_downloader import (
    DegradedArtifactError,
    M3U8Downloader,
    aes128_cbc_decrypt,
)
from app.parsers.m3u8_parser import M3U8Parser, default_iv

MEDIA_PLAIN = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:7
#EXTINF:2.0,
seg0.ts
#EXTINF:3.5,
seg1.ts
#EXTINF:4.0,
http://cdn.example.com/abs/seg2.ts
#EXT-X-ENDLIST
"""

MEDIA_AES = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-KEY:METHOD=AES-128,URI="/keys/k1.bin",IV=0x000102030405060708090a0b0c0d0e0f
#EXTINF:2.0,
seg0.ts
#EXTINF:2.0,
seg1.ts
#EXT-X-ENDLIST
"""

MEDIA_AES_NO_IV = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="k1.bin"
#EXTINF:2.0,
seg0.ts
#EXT-X-ENDLIST
"""

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1920x1080
high/index.m3u8
"""


# ---------------------------------------------------------------------------
# media playlist 解析
# ---------------------------------------------------------------------------
class TestParseMedia:
    """media playlist：时长累加、序号、URI 拼接。"""

    def test_extinf_durations_accumulate(self) -> None:
        """EXTINF 时长按序累加（2.0 + 3.5 + 4.0 = 9.5）。"""
        playlist = M3U8Parser().parse_media(MEDIA_PLAIN, "http://h.test/v/index.m3u8")
        assert [segment.duration for segment in playlist.segments] == [2.0, 3.5, 4.0]
        assert playlist.total_duration == pytest.approx(9.5)
        assert playlist.target_duration == 4.0

    def test_media_sequence_offsets_segment_sequence(self) -> None:
        """EXT-X-MEDIA-SEQUENCE 决定分片序号起点（缺省 IV 依赖它）。"""
        playlist = M3U8Parser().parse_media(MEDIA_PLAIN, "http://h.test/v/index.m3u8")
        assert playlist.media_sequence == 7
        assert [segment.sequence for segment in playlist.segments] == [7, 8, 9]
        assert [segment.index for segment in playlist.segments] == [0, 1, 2]

    def test_relative_uri_joined_with_playlist_dir(self) -> None:
        """相对 URI 按 playlist 所在目录拼接为绝对地址。"""
        playlist = M3U8Parser().parse_media(MEDIA_PLAIN, "http://h.test/v/sub/index.m3u8")
        assert playlist.segments[0].uri == "http://h.test/v/sub/seg0.ts"
        assert playlist.segments[1].uri == "http://h.test/v/sub/seg1.ts"

    def test_absolute_uri_kept(self) -> None:
        """绝对 URI 原样保留。"""
        playlist = M3U8Parser().parse_media(MEDIA_PLAIN, "http://h.test/v/index.m3u8")
        assert playlist.segments[2].uri == "http://cdn.example.com/abs/seg2.ts"

    def test_empty_playlist_raises_4006(self) -> None:
        """无可用分片 → 4006 M3U8_PARSE。"""
        with pytest.raises(BizError) as exc:
            M3U8Parser().parse_media("#EXTM3U\n#EXT-X-ENDLIST\n", "http://h.test/i.m3u8")
        assert exc.value.code == int(ErrCode.M3U8_PARSE) == 4006

    def test_master_playlist_rejected_by_parse_media(self) -> None:
        """误把 master 传给 parse_media → 4006（提示先选 variant）。"""
        with pytest.raises(BizError) as exc:
            M3U8Parser().parse_media(MASTER, "http://h.test/master.m3u8")
        assert exc.value.code == int(ErrCode.M3U8_PARSE)


# ---------------------------------------------------------------------------
# master playlist
# ---------------------------------------------------------------------------
class TestParseMaster:
    """master playlist：取最高带宽 variant。"""

    def test_picks_highest_bandwidth_variant(self) -> None:
        """取 BANDWIDTH 最大的 variant 并拼接为绝对地址。"""
        variant = M3U8Parser().parse_master(MASTER, "http://h.test/master.m3u8")
        assert variant == "http://h.test/high/index.m3u8"

    def test_returns_empty_without_variant(self) -> None:
        """非 master（无 EXT-X-STREAM-INF）→ 空字符串。"""
        assert M3U8Parser().parse_master(MEDIA_PLAIN, "http://h.test/i.m3u8") == ""

    def test_is_master_detection(self) -> None:
        """master 判定只看 EXT-X-STREAM-INF。"""
        parser = M3U8Parser()
        assert parser.is_master(MASTER) is True
        assert parser.is_master(MEDIA_PLAIN) is False


# ---------------------------------------------------------------------------
# EXT-X-KEY / DRM
# ---------------------------------------------------------------------------
class TestEncryptionKeys:
    """加密判定：AES-128 支持、SAMPLE-AES / DRM 抛 4007。"""

    def test_aes128_with_explicit_iv(self) -> None:
        """AES-128 + 显式 IV：解析出 16 字节 IV 与绝对密钥地址。"""
        playlist = M3U8Parser().parse_media(MEDIA_AES, "http://h.test/v/index.m3u8")
        key = playlist.keys[0]
        assert playlist.is_encrypted is True
        assert key.method == "AES-128"
        assert key.iv == bytes(range(16))
        assert key.uri == "http://h.test/keys/k1.bin"
        assert set(playlist.keys) == {0, 1}, "每个加密分片都要能查到密钥"

    def test_aes128_without_iv_uses_default_iv(self) -> None:
        """AES-128 无 IV：解析为 None，由下载器用序号生成缺省 IV。"""
        playlist = M3U8Parser().parse_media(
            MEDIA_AES_NO_IV, "http://h.test/v/sub/index.m3u8"
        )
        assert playlist.keys[0].iv is None
        assert playlist.keys[0].uri == "http://h.test/v/sub/k1.bin"
        assert default_iv(0) == bytes(16)
        assert default_iv(5) == (5).to_bytes(16, "big")

    def test_sample_aes_raises_4007(self) -> None:
        """SAMPLE-AES 不支持 → 4007 DRM_UNSUPPORTED。"""
        content = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k.bin"\n#EXTINF:2,\nseg0.ts\n'
        with pytest.raises(BizError) as exc:
            M3U8Parser().parse_media(content, "http://h.test/i.m3u8")
        assert exc.value.code == int(ErrCode.DRM_UNSUPPORTED) == 4007
        assert exc.value.retryable is False

    @pytest.mark.parametrize(
        "key_line",
        [
            '#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,URI="k.bin"',
            '#EXT-X-KEY:METHOD=AES-128,URI="k.bin",'
            'KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"',
            '#EXT-X-KEY:METHOD=AES-128,URI="k.bin",KEYFORMAT="com.apple.streamingkeydelivery"',
            '#EXT-X-KEY:METHOD=ISO-23001-7,URI="k.bin"',
        ],
    )
    def test_unsupported_method_or_keyformat_raises_4007(self, key_line: str) -> None:
        """SAMPLE-AES-CTR / Widevine / FairPlay / 未知方法 → 4007。"""
        content = f"#EXTM3U\n{key_line}\n#EXTINF:2,\nseg0.ts\n"
        with pytest.raises(BizError) as exc:
            M3U8Parser().parse_media(content, "http://h.test/i.m3u8")
        assert exc.value.code == int(ErrCode.DRM_UNSUPPORTED)

    def test_method_none_is_plain(self) -> None:
        """METHOD=NONE：不视为加密。"""
        content = '#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n#EXTINF:2,\nseg0.ts\n'
        playlist = M3U8Parser().parse_media(content, "http://h.test/i.m3u8")
        assert playlist.is_encrypted is False
        assert playlist.keys == {}

    @pytest.mark.parametrize(
        "key_line",
        [
            '#EXT-X-KEY:METHOD=AES-128',
            '#EXT-X-KEY:METHOD=AES-128,URI="k.bin",IV=0xZZ',
            '#EXT-X-KEY:METHOD=AES-128,URI="k.bin",IV=0x0011',
        ],
    )
    def test_invalid_key_line_raises_4006(self, key_line: str) -> None:
        """缺 URI / IV 非十六进制 / IV 长度非 16 → 4006。"""
        content = f"#EXTM3U\n{key_line}\n#EXTINF:2,\nseg0.ts\n"
        with pytest.raises(BizError) as exc:
            M3U8Parser().parse_media(content, "http://h.test/i.m3u8")
        assert exc.value.code == int(ErrCode.M3U8_PARSE)


# ---------------------------------------------------------------------------
# AES-128-CBC 加解密（NIST SP 800-38A 向量）
# ---------------------------------------------------------------------------
NIST_KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
NIST_IV = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
NIST_CIPHER = bytes.fromhex(
    "7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"
)
NIST_PLAIN = bytes.fromhex(
    "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
)


class TestAes128:
    """AES-128-CBC 解密实现：pycryptodome 路径与纯 Python 兜底路径都必须正确。"""

    def test_nist_vector_with_pycryptodome(self) -> None:
        """pycryptodome 路径：NIST 向量解密结果一致。"""
        assert aes128_cbc_decrypt(NIST_CIPHER, NIST_KEY, NIST_IV) == NIST_PLAIN

    def test_nist_vector_with_pure_python(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """纯 Python 兜底路径：同一向量解密结果一致。"""
        monkeypatch.setattr(downloader_module, "_HAS_PYCRYPTODOME", False)
        assert aes128_cbc_decrypt(NIST_CIPHER, NIST_KEY, NIST_IV) == NIST_PLAIN

    @pytest.mark.parametrize("pure", [False, True])
    def test_roundtrip_with_pkcs7(self, monkeypatch: pytest.MonkeyPatch, pure: bool) -> None:
        """加密 → 解密往返：中文分片内容完全还原（含 PKCS#7 去填充）。"""
        if pure:
            monkeypatch.setattr(downloader_module, "_HAS_PYCRYPTODOME", False)
        plaintext = "这是一段中文分片内容，用于验证 AES-128-CBC 往返。".encode("utf-8") * 3
        cipher = AES.new(NIST_KEY, AES.MODE_CBC, NIST_IV).encrypt(pad(plaintext, 16))
        assert aes128_cbc_decrypt(cipher, NIST_KEY, NIST_IV) == plaintext

    @pytest.mark.parametrize(("key", "iv"), [(b"short", bytes(16)), (bytes(16), b"short")])
    def test_invalid_key_or_iv_length_rejected(self, key: bytes, iv: bytes) -> None:
        """密钥 / IV 长度不是 16 字节 → 4006。"""
        with pytest.raises(BizError) as exc:
            aes128_cbc_decrypt(bytes(16), key, iv)
        assert exc.value.code == int(ErrCode.M3U8_PARSE)

    def test_non_padded_tail_is_ignored(self) -> None:
        """密文尾部不足 16 字节：忽略残块不报错（真实站点偶见截断）。"""
        assert aes128_cbc_decrypt(NIST_CIPHER + b"\x01\x02", NIST_KEY, NIST_IV) == NIST_PLAIN


# ---------------------------------------------------------------------------
# 下载器集成（本地模拟站点，无 ffmpeg）
# ---------------------------------------------------------------------------
class _NoFfmpeg:
    """ffmpeg 缺失替身（触发降级路径，便于校验分片内容）。"""

    available = False
    version = None
    path = None

    def probe_duration(self, _path: Any) -> float:
        return 0.0

    def to_mp4(self, _src: Any, _dst: Any, **_kwargs: Any) -> str:
        raise AssertionError("ffmpeg 不可用时不应调用 to_mp4")


class TestDownloaderIntegration:
    """走真实 HTTP（本地站点）验证分片并发、解密、concat 与降级产物。"""

    def test_plain_playlist_download_and_concat(
        self, site: Any, tmp_path: Path
    ) -> None:
        """明文 playlist：分片下载 + 按序拼接 + 降级 .ts 内容正确。"""
        site.m3u8_mode = "plain"
        downloader = M3U8Downloader(http=HttpClient(), converter=_NoFfmpeg())
        fallback = tmp_path / "out" / "video.ts"
        with pytest.raises(DegradedArtifactError) as exc:
            downloader.download(
                site.url("media/1/index.m3u8"),
                task_id=101,
                work_dir=str(tmp_path / "work"),
                ts_fallback_path=str(fallback),
            )
        expected = b"".join(site.plain_segment(1, index) for index in range(site.segment_count))
        assert Path(exc.value.artifact_path).read_bytes() == expected
        assert exc.value.code == int(ErrCode.FFMPEG_MISSING) == 3003

    def test_aes128_playlist_is_decrypted_before_concat(
        self, site: Any, tmp_path: Path
    ) -> None:
        """AES-128（显式 IV）分片：解密后拼接内容与明文分片一致。"""
        site.m3u8_mode = "aes128"
        downloader = M3U8Downloader(http=HttpClient(), converter=_NoFfmpeg())
        fallback = tmp_path / "out" / "video.ts"
        with pytest.raises(DegradedArtifactError) as exc:
            downloader.download(
                site.url("media/2/index.m3u8"),
                task_id=102,
                work_dir=str(tmp_path / "work2"),
                ts_fallback_path=str(fallback),
            )
        site.m3u8_mode = "plain"
        expected = b"".join(site.plain_segment(2, index) for index in range(site.segment_count))
        assert Path(exc.value.artifact_path).read_bytes() == expected

    def test_aes128_without_explicit_iv_uses_sequence(
        self, site: Any, tmp_path: Path
    ) -> None:
        """AES-128（缺省 IV = 分片序号大端）同样可解密。"""
        site.m3u8_mode = "aes128_no_iv"
        downloader = M3U8Downloader(http=HttpClient(), converter=_NoFfmpeg())
        with pytest.raises(DegradedArtifactError) as exc:
            downloader.download(
                site.url("media/3/index.m3u8"),
                task_id=103,
                work_dir=str(tmp_path / "work3"),
                ts_fallback_path=str(tmp_path / "out" / "v3.ts"),
            )
        site.m3u8_mode = "plain"
        expected = b"".join(site.plain_segment(3, index) for index in range(site.segment_count))
        assert Path(exc.value.artifact_path).read_bytes() == expected

    def test_sample_aes_playlist_fails_with_4007(
        self, site: Any, tmp_path: Path
    ) -> None:
        """SAMPLE-AES 流：下载阶段直接 4007，不产出任何文件。"""
        site.m3u8_mode = "sample_aes"
        downloader = M3U8Downloader(http=HttpClient(), converter=_NoFfmpeg())
        with pytest.raises(BizError) as exc:
            downloader.download(
                site.url("media/1/index.m3u8"),
                task_id=104,
                work_dir=str(tmp_path / "work4"),
                ts_fallback_path=str(tmp_path / "out" / "v4.ts"),
            )
        assert exc.value.code == int(ErrCode.DRM_UNSUPPORTED)
        assert not (tmp_path / "out" / "v4.ts").exists()

    def test_missing_segment_raises_http_error(
        self, site: Any, tmp_path: Path
    ) -> None:
        """分片 404：重试 2 次后失败，错误码 4005 且可重试。"""
        site.status_overrides["/media/1/seg1.ts"] = 404
        downloader = M3U8Downloader(http=HttpClient(), converter=_NoFfmpeg())
        with pytest.raises(BizError) as exc:
            downloader.download(
                site.url("media/1/index.m3u8"),
                task_id=105,
                work_dir=str(tmp_path / "work5"),
                ts_fallback_path=str(tmp_path / "out" / "v5.ts"),
            )
        assert exc.value.code == int(ErrCode.HTTP_ERROR)
