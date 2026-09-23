"""Render carousel slides into a LinkedIn-ready PDF (document post).

1080 x 1350 px portrait pages (LinkedIn's recommended 4:5 carousel size),
Hyperclients-style dark theme, large readable type, slide counter. Pure
Python (reportlab) - no browser or external service involved.
"""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

WIDTH, HEIGHT = 1080, 1350
MARGIN = 96
BG = HexColor("#0B1628")
ACCENT = HexColor("#13E0C2")
TEXT = HexColor("#F2F6FA")
MUTED = HexColor("#9FB3C8")
FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        words, line = para.split(), ""
        for w in words:
            trial = f"{line} {w}".strip()
            if stringWidth(trial, font, size) <= max_width:
                line = trial
            else:
                if line:
                    lines.append(line)
                while stringWidth(w, font, size) > max_width and len(w) > 1:  # hard-split huge words
                    cut = len(w)
                    while cut > 1 and stringWidth(w[:cut], font, size) > max_width:
                        cut -= 1
                    lines.append(w[:cut])
                    w = w[cut:]
                line = w
        lines.append(line)
    return [ln for ln in lines]


def _fit(text: str, font: str, start: int, minimum: int, max_width: float, max_lines: int) -> tuple[int, list[str]]:
    size = start
    while size > minimum:
        lines = _wrap(text, font, size, max_width)
        if len(lines) <= max_lines:
            return size, lines
        size -= 4
    return minimum, _wrap(text, font, minimum, max_width)[:max_lines]


def render_carousel(slides: list[dict[str, Any]], *, author: str = "", handle: str = "") -> bytes:
    """slides: [{"title", "body"}] -> PDF bytes (one slide per page)."""
    if not slides:
        raise ValueError("at least one slide is required")
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(WIDTH, HEIGHT))
    pdf.setTitle(str(slides[0].get("title") or "Carousel"))
    total = len(slides)
    usable = WIDTH - 2 * MARGIN
    for idx, slide in enumerate(slides, start=1):
        pdf.setFillColor(BG)
        pdf.rect(0, 0, WIDTH, HEIGHT, stroke=0, fill=1)
        pdf.setFillColor(ACCENT)
        pdf.rect(MARGIN, HEIGHT - MARGIN - 12, 120, 12, stroke=0, fill=1)

        first = idx == 1
        title_size, title_lines = _fit(str(slide.get("title") or ""), FONT_BOLD,
                                       96 if first else 72, 40, usable, 6 if first else 4)
        y = HEIGHT - MARGIN - 110
        pdf.setFillColor(TEXT)
        pdf.setFont(FONT_BOLD, title_size)
        for line in title_lines:
            y -= title_size * 1.15
            pdf.drawString(MARGIN, y, line)

        body = str(slide.get("body") or "")
        if body:
            body_size, body_lines = _fit(body, FONT, 50 if not first else 44, 28, usable, 12)
            y -= body_size * 1.4
            pdf.setFillColor(MUTED if first else TEXT)
            pdf.setFont(FONT, body_size)
            for line in body_lines:
                y -= body_size * 1.35
                pdf.drawString(MARGIN, y, line)

        pdf.setFillColor(MUTED)
        pdf.setFont(FONT, 30)
        footer = " · ".join(x for x in (author, handle) if x)
        if footer:
            pdf.drawString(MARGIN, MARGIN - 10, footer[:60])
        counter = f"{idx}/{total}"
        pdf.drawRightString(WIDTH - MARGIN, MARGIN - 10, counter + ("   swipe >" if idx < total else ""))
        pdf.showPage()
    pdf.save()
    return buf.getvalue()
