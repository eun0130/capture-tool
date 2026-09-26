"""Paint annotations with QPainter — shared by the live overlay and the exported image."""
from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from ..core.annotations import Document, Shape

FONT_FAMILY = "Malgun Gothic"


def bgr_to_qimage(img: np.ndarray) -> QImage:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    q = QImage(img.data, w, h, img.strides[0], QImage.Format_BGR888)
    return q.copy()  # detach from numpy buffer


def qimage_to_bgr(q: QImage) -> np.ndarray:
    q = q.convertToFormat(QImage.Format_BGR888)
    h, w = q.height(), q.width()
    arr = np.frombuffer(q.constBits(), np.uint8).reshape(h, q.bytesPerLine())[:, :w * 3]
    return arr.reshape(h, w, 3).copy()


def bgr_to_pixmap(img: np.ndarray, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap.fromImage(bgr_to_qimage(img))
    pm.setDevicePixelRatio(dpr)
    return pm


def apply_mosaic(img: np.ndarray, shapes: list[Shape], block: int = 12) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    for s in shapes:
        if s.kind != "mosaic":
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in s.bbox())
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        roi = out[y1:y2, x1:x2]
        small = cv2.resize(roi, (max(1, (x2 - x1) // block), max(1, (y2 - y1) // block)), interpolation=cv2.INTER_AREA)
        out[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
    return out


def arrow_head(x1, y1, x2, y2, width) -> tuple[QPolygonF, QPointF]:
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    size = 4 * width + 8
    bx, by = x2 - ux * size, y2 - uy * size
    half = size * 0.55
    poly = QPolygonF([QPointF(x2, y2), QPointF(bx - uy * half, by + ux * half), QPointF(bx + uy * half, by - ux * half)])
    return poly, QPointF(bx, by)


def paint_shape(p: QPainter, s: Shape) -> None:
    color = QColor(s.color)
    p.save()
    p.setOpacity(s.opacity)
    pen = QPen(color, s.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    pts = [QPointF(x, y) for x, y in s.points]
    if s.kind in ("rect", "ellipse", "highlight"):
        r = QRectF(pts[0], pts[1]).normalized()
        if s.kind == "highlight":
            c = QColor(color)
            c.setAlphaF(0.35)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRect(r)
        else:
            if s.fill:
                p.setBrush(QBrush(color))
            (p.drawRect if s.kind == "rect" else p.drawEllipse)(r)
    elif s.kind == "line":
        p.drawLine(pts[0], pts[1])
    elif s.kind == "arrow":
        poly, base = arrow_head(pts[0].x(), pts[0].y(), pts[1].x(), pts[1].y(), s.width)
        p.drawLine(pts[0], base)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon(poly)
    elif s.kind in ("pen", "curve"):
        path = QPainterPath(pts[0])
        if s.kind == "curve" and len(pts) > 2:
            for i in range(1, len(pts) - 1):
                mid = (pts[i] + pts[i + 1]) / 2
                path.quadTo(pts[i], mid)
            path.lineTo(pts[-1])
        else:
            for q in pts[1:]:
                path.lineTo(q)
        p.drawPath(path)
    elif s.kind == "text":
        f = QFont(FONT_FAMILY)
        f.setPixelSize(int(14 + s.width * 2))
        f.setBold(True)
        p.setFont(f)
        y = pts[0].y()
        for line in (s.text or "").split("\n"):
            y += f.pixelSize() * 1.25
            p.drawText(QPointF(pts[0].x(), y - f.pixelSize() * 0.25), line)
    elif s.kind == "step":
        r = 14
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(pts[0], r, r)
        f = QFont(FONT_FAMILY)
        f.setPixelSize(15)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(pts[0].x() - r, pts[0].y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(s.number))
    p.restore()


def paint_document(p: QPainter, shapes: list[Shape]) -> None:
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    for s in shapes:
        if s.kind != "mosaic":
            paint_shape(p, s)


def compose(img: np.ndarray, doc: Document | None) -> np.ndarray:
    """Final exported image: capture + mosaic + vector annotations."""
    if doc is None or not doc.shapes:
        return img.copy()
    base = apply_mosaic(img, doc.shapes)
    q = bgr_to_qimage(base)
    p = QPainter(q)
    paint_document(p, doc.shapes)
    p.end()
    return qimage_to_bgr(q)
