"""文字落盘：TXT 编码与 PDF 中文字体（ToUnicode / 不乱码）+ 导出格式端到端。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import support
from app.config import E
from app.downloader import text_writer as text_writer_module
from app.downloader.text_writer import CID_FONT, TextWriter

CHINESE_TITLE = "第001章 科学边界"
CHINESE_BODY = "这是中文正文，用于验证 PDF 字体嵌入与 ToUnicode 映射，不能出现方块。"


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------
class TestTxtWriter:
    """TXT：UTF-8、标题 + 空行 + 正文、原子写。"""

    def test_txt_is_utf8_with_title_and_body(self, tmp_path: Path) -> None:
        """落盘内容为 UTF-8 且含标题与正文，大小与返回值一致。"""
        target = tmp_path / "章" / "第001章.txt"
        size = TextWriter().write_txt(target, CHINESE_TITLE, CHINESE_BODY)

        assert target.exists()
        assert size == target.stat().st_size > 0
        text = target.read_text(encoding="utf-8")
        assert text.startswith(CHINESE_TITLE)
        assert CHINESE_BODY in text
        assert not list(target.parent.glob("*.part")), "不得残留 .part 临时文件"

    def test_txt_normalizes_crlf(self, tmp_path: Path) -> None:
        """CRLF / CR 统一为 LF。"""
        target = tmp_path / "a.txt"
        TextWriter().write_txt(target, "标题", "第一行\r\n第二行\r第三行")
        content = target.read_text(encoding="utf-8")
        assert "第二行\r" not in content
        assert "第一行\n第二行\n第三行" in content


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
class TestPdfWriter:
    """PDF：中文字体嵌入 + 可抽取中文（无方块）。"""

    def test_pdf_embeds_font_and_keeps_chinese(self, tmp_path: Path) -> None:
        """PDF 体积 > 2KB、含嵌入字体与 ToUnicode，抽取文本仍是中文。"""
        target = tmp_path / "第001章.pdf"
        size = TextWriter().write_pdf(target, CHINESE_TITLE, CHINESE_BODY)
        data = target.read_bytes()

        assert data.startswith(b"%PDF")
        assert size == len(data) > 2048, f"PDF 体积可疑：{size}"
        assert b"/FontFile2" in data or b"/FontFile3" in data or b"STSong-Light" in data, (
            "PDF 缺少字体嵌入标记，中文可能显示为方块"
        )
        assert b"/ToUnicode" in data or b"STSong-Light" in data, "缺少 ToUnicode 映射"

        pdfminer = pytest.importorskip("pdfminer.high_level", reason="未安装 pdfminer.six")
        extracted = pdfminer.extract_text(str(target))
        assert CHINESE_TITLE in extracted
        assert "中文正文" in extracted
        assert "\ufffd" not in extracted and "□" not in extracted

    def test_pdf_falls_back_to_cid_font(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """系统字体全部缺失时回退内置 CID 字体，仍能生成可读 PDF。"""
        monkeypatch.setattr(text_writer_module, "FONT_CANDIDATES", ())
        monkeypatch.setattr(TextWriter, "_font_name", None)
        target = tmp_path / "cid.pdf"
        size = TextWriter().write_pdf(target, "中文标题", "中文正文内容")
        data = target.read_bytes()

        assert size > 1024
        assert CID_FONT.encode() in data, "未回退到内置 CID 字体 STSong-Light"
        assert not list(tmp_path.glob("*.part*")), "不得残留 .part 临时文件"

    def test_pdf_escapes_markup_characters(self, tmp_path: Path) -> None:
        """正文含 XML 特殊字符不得导致 reportlab 抛异常。"""
        target = tmp_path / "escape.pdf"
        size = TextWriter().write_pdf(target, "标题 <b>", "正文 & <tag> \"引号\"")
        assert size > 0


# ---------------------------------------------------------------------------
# 端到端：export_format=pdf
# ---------------------------------------------------------------------------
class TestPdfExportEndToEnd:
    """PRD P0-12③：选择 pdf 时同路径换成 .pdf 且可被阅读器打开。"""

    def test_pdf_export_produces_pdf_artifact(self, client: TestClient, site: Any) -> None:
        """批次 export_format=pdf → 产物类型 pdf 且文件真实存在。"""
        ds_id = support.create_source(client, site, name="PDF小说源", is_novel=False)
        batch_id = support.create_batch(
            client, ds_id, E.STRATEGY_COUNT, {"n": 1}, export_format=E.FORMAT_PDF
        )
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_SUCCESS
        assert detail["export_format"] == E.FORMAT_PDF

        artifact = support.artifacts_of(client, ds_id)[0]
        path = Path(artifact["path"])
        assert artifact["type"] == E.ARTIFACT_PDF
        assert path.suffix == ".pdf"
        assert path.stat().st_size > 1024
        assert path.read_bytes().startswith(b"%PDF")
        # TXT 也应在同目录保留（DEV-09：始终先写 TXT）
        assert path.with_suffix(".txt").exists()

    def test_pdf_failure_does_not_fail_task(
        self, client: TestClient, site: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PDF 生成失败只 WARN：任务仍成功，产物类型回退 text（DEV-09）。"""
        def _boom(*_args: Any, **_kwargs: Any) -> int:
            raise RuntimeError("模拟 reportlab 渲染失败")

        monkeypatch.setattr(TextWriter, "write_pdf", _boom)
        ds_id = support.create_source(client, site, name="PDF降级源", is_novel=False)
        batch_id = support.create_batch(
            client, ds_id, E.STRATEGY_COUNT, {"n": 1}, export_format=E.FORMAT_PDF
        )
        detail = support.wait_batch(client, batch_id)
        assert detail["status"] == E.BATCH_SUCCESS
        assert detail["done_tasks"] == 1

        artifact = support.artifacts_of(client, ds_id)[0]
        assert artifact["type"] == E.ARTIFACT_TEXT
        assert Path(artifact["path"]).suffix == ".txt"
        assert Path(artifact["path"]).stat().st_size > 0

        logs = support.unwrap(
            client.get(f"/api/batches/{batch_id}/logs", params={"level": "WARN"})
        )
        assert any("PDF" in item["message"] for item in logs["items"])
