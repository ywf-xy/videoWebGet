"""文字落盘：TXT（UTF-8）与 PDF（reportlab，注册中文字体保证不乱码）。

PDF 字体策略（A-07）：
1. 依次尝试系统 ``msyh.ttc`` / ``msyhbd.ttc`` / ``simhei.ttf`` / ``simsun.ttc`` / Noto Sans SC；
2. 全部缺失时使用 reportlab 内置 CID 字体 ``STSong-Light``（``UnicodeCIDFont``），
   保证中文不出现方块。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

from app.common.logger import get_logger

logger = get_logger(__name__)

#: 候选中文字体（按优先级）
FONT_CANDIDATES: Final[tuple[str, ...]] = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

#: reportlab 内置 CID 字体（最终兜底）
CID_FONT: Final[str] = "STSong-Light"
#: 注册到 reportlab 的字体别名
FONT_ALIAS: Final[str] = "CrawlerHubCJK"


class TextWriter:
    """TXT / PDF writer（线程安全的字体注册）。"""

    _font_lock = threading.Lock()
    _font_name: str | None = None

    # ------------------------------------------------------------------
    # TXT
    # ------------------------------------------------------------------
    def write_txt(self, path: str | Path, title: str, content: str) -> int:
        """写入 TXT（UTF-8，标题 + 空行 + 正文），返回文件字节数。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        body = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        text = f"{title}\n\n{body}\n" if title else f"{body}\n"
        part = target.with_name(f"{target.name}.part")
        part.write_text(text, encoding="utf-8")
        part.replace(target)
        return target.stat().st_size

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------
    def write_pdf(self, path: str | Path, title: str, content: str) -> int:
        """写入 PDF，返回文件字节数。

        Raises:
            RuntimeError: reportlab 缺失或渲染失败（调用方应降级为仅 TXT）。
        """
        from reportlab.lib.pagesizes import A4  # 延迟导入，缩短启动时间
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        font_name = self._ensure_font()

        body_style = ParagraphStyle(
            "CrawlerHubBody",
            fontName=font_name,
            fontSize=11,
            leading=20,
            spaceAfter=6,
            wordWrap="CJK",
        )
        title_style = ParagraphStyle(
            "CrawlerHubTitle",
            parent=body_style,
            fontSize=18,
            leading=28,
            spaceAfter=14,
        )

        story: list[object] = []
        if title:
            story.append(Paragraph(escape(title), title_style))
        body = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        for block in body.split("\n"):
            line = block.strip()
            if not line:
                story.append(Spacer(1, 6))
                continue
            story.append(Paragraph(escape(line), body_style))
        if not story:
            story.append(Paragraph(escape(title or "（空内容）"), body_style))

        part = target.with_name(f"{target.stem}.part{target.suffix or '.pdf'}")
        document = SimpleDocTemplate(
            str(part),
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title=title or target.stem,
        )
        document.build(story)
        part.replace(target)
        return target.stat().st_size

    # ------------------------------------------------------------------
    # 字体
    # ------------------------------------------------------------------
    def _ensure_font(self) -> str:
        """注册中文字体（幂等），返回可用字体名。"""
        with self._font_lock:
            if self._font_name:
                return self._font_name

            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfbase.ttfonts import TTFont

            for candidate in FONT_CANDIDATES:
                font_path = Path(candidate)
                if not font_path.exists():
                    continue
                try:
                    if font_path.suffix.lower() == ".ttc":
                        pdfmetrics.registerFont(TTFont(FONT_ALIAS, str(font_path), subfontIndex=0))
                    else:
                        pdfmetrics.registerFont(TTFont(FONT_ALIAS, str(font_path)))
                    TextWriter._font_name = FONT_ALIAS
                    logger.info("PDF 中文字体注册成功：%s", font_path)
                    return FONT_ALIAS
                except Exception as exc:  # noqa: BLE001 - 字体文件可能损坏
                    logger.warning("注册字体失败 %s：%s", font_path, exc)

            pdfmetrics.registerFont(UnicodeCIDFont(CID_FONT))
            TextWriter._font_name = CID_FONT
            logger.warning("未找到系统中文字体，PDF 回退内置 CID 字体 %s", CID_FONT)
            return CID_FONT
