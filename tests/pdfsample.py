"""A realistic multi-page PDF for scroll-capture tests: page headers, paragraphs, horizontal
rules, photo-like images, a table, and a blank page — the things PDF viewers show."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

PAGE_COLORS = ["#1C64D8", "#E03131", "#2F9E44", "#F08C00", "#7048E8", "#0C8599", "#C2255C", "#5C940D"]


def photo(w: int, h: int, seed: int) -> QImage:
    """Smooth photo-like texture (gradients + blobs + noise): scaled by the viewer, it never
    renders exactly the same twice at fractional scroll offsets."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    for c in range(3):
        img[..., c] = 128 + 60 * np.sin(x / (20 + 7 * c + seed) + y / (35 + seed)) \
                      + 40 * np.cos((x + y) / (50 + 11 * c))
    for _ in range(6):
        cx, cy, r = rng.integers(0, w), rng.integers(0, h), rng.integers(20, 90)
        img += 70 * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * r * r))[..., None] * rng.uniform(-1, 1, 3)
    img += rng.normal(0, 8, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    q = QImage(img.data, w, h, 3 * w, QImage.Format_RGB888)
    return q.copy()


def make_pdf(path, pages: int = 6, blank_page: int | None = 3) -> list[str]:
    """Write the PDF; returns each page's marker color (drawn as a bar at the page top)."""
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(0, 0, 0, 0))
    w.setResolution(96)
    p = QPainter(w)
    W, H = w.width(), w.height()
    colors = []
    for n in range(pages):
        if n:
            w.newPage()
        color = PAGE_COLORS[n % len(PAGE_COLORS)]
        colors.append(color)
        p.fillRect(QRectF(0, 0, W, 40), QColor(color))            # page marker bar
        if n == blank_page:
            continue                                               # (almost) blank page
        f = QFont("Arial")
        f.setPixelSize(22)
        p.setFont(f)
        p.setPen(QColor("#000000"))
        p.drawText(QRectF(40, 60, W - 80, 30), Qt.AlignLeft, f"PAGE {n + 1} - Quarterly report section")
        f.setPixelSize(13)
        p.setFont(f)
        y = 110
        for i in range(6):
            p.drawText(QRectF(40, y, W - 80, 20), Qt.AlignLeft,
                       f"Line {i + 1} of page {n + 1}: revenue, margins and outlook are discussed here.")
            y += 22
        p.setPen(QPen(QColor("#888888"), 2))
        p.drawLine(40, y + 10, W - 40, y + 10)                     # separator rule
        img = photo(W - 160, 300, seed=n + 1)
        p.drawImage(QRectF(80, y + 30, W - 160, 300), img)         # photo, scaled by the viewer
        y += 350
        p.setPen(QPen(QColor("#888888"), 1))
        for r in range(8):                                          # a ruled table
            p.drawLine(40, y + r * 28, W - 40, y + r * 28)
            p.setPen(QColor("#000000"))
            p.drawText(QRectF(50, y + r * 28 + 5, 300, 20), Qt.AlignLeft, f"Item {r + 1}")
            p.setPen(QPen(QColor("#888888"), 1))
        y += 8 * 28 + 20
        p.drawLine(40, y, W - 40, y)
        img2 = photo(W - 80, 200, seed=100 + n)
        p.drawImage(QRectF(40, y + 20, W - 80, 200), img2)
    p.end()
    return colors
