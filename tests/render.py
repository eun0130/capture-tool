"""Render Korean/English text into a BGR image with a real font (headless Qt)."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter

_family = None


def _font(size: int) -> QFont:
    global _family
    if _family is None:
        fid = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\malgun.ttf")
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _family = fams[0] if fams else "Sans Serif"
    return QFont(_family, size)


def render_text(lines: list[str], width: int = 900, size: int = 20) -> np.ndarray:
    h = 40 + 60 * len(lines)
    img = QImage(width, h, QImage.Format_RGB888)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setFont(_font(size))
    p.setPen(QColor("black"))
    for i, t in enumerate(lines):
        p.drawText(20, 50 + 60 * i, t)
    p.end()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :width * 3]
    return arr.reshape(h, width, 3)[:, :, ::-1].copy()
