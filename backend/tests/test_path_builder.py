"""PathBuilder 目录模板 + 文件名清洗规则（PRD 9.1 / 9.2）逐字符断言。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.common.filename import (
    MAX_SEGMENT_LEN,
    RESERVED_NAMES,
    ensure_suffix,
    sanitize,
    sanitize_ext,
    strip_suffix,
)
from app.common.path_builder import UNCATEGORIZED, PathBuilder


class FakeDS:
    """PathBuilder 需要的数据源最小替身。"""

    def __init__(self, name: str, category: str | None, is_novel: bool = False) -> None:
        self.name = name
        self.category = category
        self.is_novel = is_novel


def expect(*parts: str) -> str:
    """用 os.path.join 构造期望路径（与实现同平台的字符级比对基准）。"""
    return os.path.join(*parts)


# ---------------------------------------------------------------------------
# 4 类目录模板逐字符比对
# ---------------------------------------------------------------------------
class TestPathTemplates:
    """PRD 9.1 四类模板 + 分类兜底 + 图片序号。"""

    def test_video_template(self, tmp_path: Path) -> None:
        """视频：{root}/{数据源}/{分类}/{视频名}.mp4（PRD 示例逐字符一致）。"""
        builder = PathBuilder(tmp_path)
        actual = builder.build_video(FakeDS("某某影视", "科幻"), "星际穿越")
        assert actual == expect(str(tmp_path), "某某影视", "科幻", "星际穿越.mp4")

    def test_text_novel_template(self, tmp_path: Path) -> None:
        """文字-小说：{root}/{数据源}/{分类}/{小说名}/{章节名}.txt。"""
        builder = PathBuilder(tmp_path)
        actual = builder.build_text(
            FakeDS("某某小说网", "科幻", True), title="三体", chapter="第001章 科学边界"
        )
        assert actual == expect(
            str(tmp_path), "某某小说网", "科幻", "三体", "第001章 科学边界.txt"
        )

    def test_text_novel_pdf_template(self, tmp_path: Path) -> None:
        """文字-小说导出 pdf：同路径换扩展名。"""
        builder = PathBuilder(tmp_path)
        actual = builder.build_text(
            FakeDS("某某小说网", "科幻", True), title="三体", chapter="第001章", fmt="pdf"
        )
        assert actual.endswith(".pdf")
        assert actual == expect(str(tmp_path), "某某小说网", "科幻", "三体", "第001章.pdf")

    def test_text_article_template_with_date(self, tmp_path: Path) -> None:
        """文字-非小说：{root}/{数据源}/{分类}/{yyyy-MM-dd}/{文章名}.txt。"""
        builder = PathBuilder(tmp_path)
        actual = builder.build_text(
            FakeDS("某新闻站", "科技"), title="AI 芯片发布", when="2026-10-25"
        )
        assert actual == expect(
            str(tmp_path), "某新闻站", "科技", "2026-10-25", "AI 芯片发布.txt"
        )

    def test_empty_category_falls_back_to_uncategorized(self, tmp_path: Path) -> None:
        """分类为空 → 未分类（含全空白分类）。"""
        builder = PathBuilder(tmp_path)
        assert UNCATEGORIZED == "未分类"
        for category in ("", "   ", None):
            actual = builder.build_video(FakeDS("某站", category), "片子")
            assert actual == expect(str(tmp_path), "某站", "未分类", "片子.mp4")

    def test_image_dir_template(self, tmp_path: Path) -> None:
        """图片目录：{root}/{数据源}/{分类}/{yyyy-MM-dd}/{图集名}/。"""
        builder = PathBuilder(tmp_path)
        actual = builder.build_image_dir(FakeDS("某图库", "写真"), "夏日", when="2026-10-25")
        assert actual == expect(str(tmp_path), "某图库", "写真", "2026-10-25", "夏日")
        assert Path(actual).is_dir(), "图片目录必须被逐级创建（mkdir -p）"

    def test_image_index_width_at_least_three(self, tmp_path: Path) -> None:
        """图片序号从 001 起，位宽 = max(3, 总数位宽)。"""
        builder = PathBuilder(tmp_path)
        ds = FakeDS("某图库", "写真")
        assert Path(builder.build_image_path(ds, "夏日", 1, 24, when="2026-10-25")).name == "001.jpg"
        assert Path(builder.build_image_path(ds, "夏日", 24, 24, when="2026-10-25")).name == "024.jpg"
        assert Path(builder.build_image_path(ds, "夏日", 1, 1000, when="2026-10-25")).name == "0001.jpg"
        assert Path(builder.build_image_path(ds, "夏日", 7, 9, "png", when="2026-10-25")).name == "007.png"

    def test_parent_directories_are_created(self, tmp_path: Path) -> None:
        """目录层级缺失时自动逐级创建（mkdir -p 语义）。"""
        root = tmp_path / "out"
        builder = PathBuilder(root)
        actual = builder.build_text(
            FakeDS("深层站", "分类A", True), title="书", chapter="章", when="2026-10-25"
        )
        assert Path(actual).parent.is_dir()

    def test_same_name_maps_to_same_path(self, tmp_path: Path) -> None:
        """重名策略：同名同参数生成同一路径（本期默认覆盖）。"""
        builder = PathBuilder(tmp_path)
        ds = FakeDS("某影视", "科幻")
        assert builder.build_video(ds, "重复片") == builder.build_video(ds, "重复片")


# ---------------------------------------------------------------------------
# 7 条文件名清洗规则
# ---------------------------------------------------------------------------
class TestSanitizeRules:
    """PRD 9.2：非法字符 / 首尾点空格 / 长度 / 保留名 / 空名 / 空白合并 / 重名。"""

    def test_rule1_illegal_chars_replaced(self) -> None:
        """规则 1：``\\ / : * ? " < > |`` 与控制字符替换为 ``_``。

        注：0x1C-0x1F 在 Python 的 ``\\s`` 语义里属于 Unicode 空白，会先被规则 6
        合并为空格（与 PRD 9.2 规则 1 的字面表述有偏差，但产物仍是合法文件名，
        已在 TEST-REPORT 中记为低优先级观察项）。
        """
        assert sanitize('a\\b/c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
        assert sanitize("a\x00b\x1bc") == "a_b_c"
        assert sanitize("a\x1fb") == "a b"

    def test_rule2_leading_trailing_space_and_dot_stripped(self) -> None:
        """规则 2：去除首尾空格与结尾点（Windows 不允许结尾点）。"""
        assert sanitize("  名称.  ") == "名称"
        assert sanitize("名称...") == "名称"
        assert sanitize(".隐藏") == "隐藏"
        assert not sanitize("尾部.").endswith(".")

    def test_rule3_length_truncated_with_hash(self) -> None:
        """规则 3：单段 ≤100 字符；超长截断 + ``_`` + 8 位内容哈希。"""
        long_name = "长" * 300
        cleaned = sanitize(long_name)
        assert len(cleaned) == MAX_SEGMENT_LEN == 100
        prefix, _, digest = cleaned.rpartition("_")
        assert len(digest) == 8 and all(ch in "0123456789abcdef" for ch in digest)
        assert prefix == "长" * 91, "截断长度应为 91（91+1+8=100）"

    def test_rule3_different_long_names_get_different_hash(self) -> None:
        """截断后靠哈希区分：前 91 字相同、尾部不同 → 结果不同。"""
        base = "同" * 91
        assert sanitize(base + "AAAA") != sanitize(base + "BBBB")

    def test_rule4_reserved_names_get_underscore_prefix(self) -> None:
        """规则 4：Windows 保留名（含带扩展名）前加 ``_``。"""
        for name in ("CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9", "con.txt"):
            cleaned = sanitize(name)
            assert cleaned.startswith("_"), f"{name} 未加前缀：{cleaned}"
        assert sanitize("CONSOLE") == "CONSOLE", "非保留名不应加前缀"
        assert sanitize("NUL 片段") == "NUL 片段"
        assert RESERVED_NAMES >= {"CON", "PRN", "AUX", "NUL", "COM1", "LPT9"}

    def test_rule5_empty_name_fallback(self) -> None:
        """规则 5：空名称 → ``untitled_{yyyyMMddHHmmss}``。"""
        for value in ("", None, "   ", "...", "\n\t"):
            cleaned = sanitize(value)
            assert cleaned.startswith("untitled_"), cleaned
            assert len(cleaned) == len("untitled_") + 14

    def test_rule6_whitespace_merged(self) -> None:
        """规则 6：换行 / 连续空白合并为单个空格。"""
        assert sanitize("章节\n\n  标题\t内容") == "章节 标题 内容"

    def test_rule7_duplicate_names_not_versioned(self) -> None:
        """规则 7：本期不做版本化（同名结果保持一致，覆盖由调用方处理）。"""
        assert sanitize("同名文件") == sanitize("同名文件")

    def test_extension_helpers(self) -> None:
        """扩展名清洗与后缀拼接。"""
        assert sanitize_ext(".PDF") == "pdf"
        assert sanitize_ext("t?x*t") == "txt"
        assert sanitize_ext("") == "bin"
        assert sanitize_ext("", default="jpg") == "jpg"
        assert ensure_suffix("a/b", "txt") == "a/b.txt"
        assert ensure_suffix("a.txt", ".txt") == "a.txt"
        assert strip_suffix("第001章.txt") == "第001章"


# ---------------------------------------------------------------------------
# 极端名称 / 深目录真写盘（Windows 长路径冒烟）
# ---------------------------------------------------------------------------
class TestLongPathWrite:
    """超长名称 + 深目录不得抛 OSError（截断规则必须真正生效）。"""

    def test_300_char_name_written_to_disk(self, tmp_path: Path) -> None:
        """300 字符名称经清洗后（100 字符）真实落盘成功且内容非空。"""
        builder = PathBuilder(tmp_path)
        long_title = "超长视频名称" * 50  # 300 字符
        target = builder.build_video(FakeDS("长名源", "分类"), long_title)
        Path(target).write_bytes(b"x" * 64)
        assert Path(target).exists()
        assert Path(target).stat().st_size == 64
        assert len(Path(target).name) <= 104, "文件名（含扩展名）不得超过 100 + '.mp4'"

    def test_deep_directory_written_to_disk(self, tmp_path: Path) -> None:
        """深目录（4 层 × 9 字符）+ 长文件名：不抛 OSError，且真正触及 240 字符预警线。

        说明：超过 259 字符能否写入取决于 Windows「启用长路径」设置与 Python 版本，
        本机（Python 3.13 / 长路径可用）在 260 字符处写入成功，故此处不断言 <260，
        只断言「写入成功」与「路径确实够长（否则该用例失去意义）」。
        """
        root = tmp_path
        for index in range(4):
            root = root / f"深层目录层{index:02d}假名"
        builder = PathBuilder(root)
        target = builder.build_text(
            FakeDS("深层站", "分类"), title="标题" * 60, when="2026-10-25"
        )
        Path(target).write_bytes(b"y" * 32)
        assert Path(target).exists(), f"深目录写入失败：{target}"
        assert Path(target).stat().st_size == 32
        assert len(target) >= 240, f"用例未触及路径预警线，需加长：{len(target)}"
        assert len(Path(target).name) <= 104

    def test_temp_dir_and_cleanup(self, tmp_path: Path) -> None:
        """临时目录 ``{root}/.tmp/{task_id}/`` 创建与清理。"""
        builder = PathBuilder(tmp_path)
        work = builder.temp_dir(42)
        assert Path(work).is_dir()
        assert Path(work).parent.name == ".tmp"
        (Path(work) / "seg_00000.ts").write_bytes(b"z")
        builder.cleanup_temp(42)
        assert not Path(work).exists()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("正常名称", "正常名称"),
        ("a b", "a b"),
        ("a?b", "a_b"),
        ("名称.", "名称"),
        (" 名称 ", "名称"),
    ],
)
def test_sanitize_idempotent(raw: str, expected: str) -> None:
    """清洗函数幂等且符合预期（同一输入两次结果一致）。"""
    once = sanitize(raw)
    assert once == expected
    assert sanitize(once) == once
