"""交付物导出 PDF —— reportlab + STSong-Light（reportlab 内置的中文 CID 字体，不依赖系统字体文件）。"""

from __future__ import annotations

import io
import re

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

FONT = "STSong-Light"
_ready = False

INK = HexColor("#16223a")
ACCENT = HexColor("#1a63c4")
MUTED = HexColor("#9aa8bb")
SECOND = HexColor("#6b7a90")
RULE = HexColor("#dbe3ef")


def _ensure_font() -> None:
    global _ready
    if not _ready:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
        _ready = True


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles() -> dict[str, ParagraphStyle]:
    """所有样式都必须显式指定自定义字体，否则 reportlab 会退回 Helvetica，中文变方框。"""

    def mk(name: str, **kw) -> ParagraphStyle:
        params = {"fontName": FONT, "fontSize": 10.5, "leading": 14.6, "textColor": INK}
        params.update(kw)
        return ParagraphStyle(name, **params)

    return {
        "h1": mk("h1", fontSize=16.5, leading=23, spaceAfter=5),
        "h2": mk("h2", fontSize=12, leading=17, spaceBefore=5.5, spaceAfter=0.5, textColor=ACCENT),
        "quote": mk("quote", fontSize=10, leading=16, textColor=SECOND, leftIndent=8),
        "body": mk("body"),
        "muted": mk("muted", textColor=MUTED),
    }


def markdown_to_pdf(markdown: str, *, title: str = "", order_id: str = "", customer: str = "") -> bytes:
    """把交付物渲染出的 Markdown 转成 A4 PDF。只认工作台自己产出的这几种行，不做通用 Markdown。"""
    _ensure_font()
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=title or "交付物", author="TripCraft · 旅鸢",
                            subject=f"{title} {order_id} {customer}".strip())
    story: list = []
    for raw in (markdown or "").splitlines():
        s = raw.strip()
        if not s:
            story.append(Spacer(1, 2))
            continue
        if s.startswith("### "):
            story.append(Paragraph(_esc(s[4:]), st["h2"]))
        elif s.startswith("## "):
            story.append(Paragraph(_esc(s[3:]), st["h2"]))
        elif s.startswith("# "):
            story.append(Paragraph(_esc(s[2:]), st["h1"]))
        elif s.startswith("> "):
            story.append(Paragraph(_esc(s[2:]), st["quote"]))
        elif set(s) <= set("-—") and len(s) >= 3:
            story.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=6, spaceAfter=6))
        else:
            text = _esc(re.sub(r"\*\*(.+?)\*\*", r"\1", s))
            story.append(Paragraph(text, st["muted"] if s.startswith("（未填写）") else st["body"]))
    doc.build(story)
    return buf.getvalue()
