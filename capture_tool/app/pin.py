"""A capture pinned on top of every window: drag to move, wheel to zoom,
Ctrl+wheel for opacity, double-click to close."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from .render import bgr_to_pixmap


class PinWindow(QWidget):
    closed = Signal(object)
    copyRequested = Signal(object)
    saveRequested = Signal(object)

    def __init__(self, image, pos: QPoint, dpr: float = 1.0):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.image = image
        self.dpr = dpr
        self.pixmap = bgr_to_pixmap(image, dpr)
        self.zoom = 1.0
        self._drag: QPoint | None = None
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("드래그 이동 · 휠 확대/축소 · Ctrl+휠 투명도 · 더블클릭 닫기 · 우클릭 메뉴")
        self._resize()
        self.move(pos)

    @property
    def image_size(self) -> tuple[int, int]:
        return self.image.shape[1], self.image.shape[0]

    def _resize(self) -> None:
        w, h = self.image_size
        self.resize(max(8, round(w / self.dpr * self.zoom)), max(8, round(h / self.dpr * self.zoom)))

    def zoom_by(self, steps: int) -> None:
        self.zoom = min(4.0, max(0.2, self.zoom * (1.1 ** steps)))
        self._resize()
        self.update()

    def opacity_by(self, steps: int) -> None:
        self.setWindowOpacity(min(1.0, max(0.2, self.windowOpacity() + 0.1 * steps)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(self.rect(), self.pixmap)
        p.setPen(QPen(QColor("#1F5FD1"), 2))
        p.drawRect(QRect(0, 0, self.width() - 1, self.height() - 1))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.close()

    def wheelEvent(self, e):
        steps = 1 if e.angleDelta().y() > 0 else -1
        if e.modifiers() & Qt.ControlModifier:
            self.opacity_by(steps)
        else:
            self.zoom_by(steps)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        for label, fn in [("복사", lambda: self.copyRequested.emit(self)),
                          ("저장", lambda: self.saveRequested.emit(self)),
                          ("원래 크기", lambda: (setattr(self, "zoom", 1.0), self._resize(), self.update())),
                          ("닫기", self.close)]:
            a = QAction(label, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(e.globalPos())

    def closeEvent(self, e):
        self.closed.emit(self)
        super().closeEvent(e)
