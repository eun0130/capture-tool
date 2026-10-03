"""A capture pinned on top of every window.

Close: Esc, the ✕ button (shown on hover), double-click, or right-click → 닫기.
Move: drag. Zoom: wheel / + - 0. Opacity: Ctrl+wheel. Copy: Ctrl+C. Save: Ctrl+S."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from . import icons
from .render import bgr_to_pixmap


MIN_ZOOM = 0.05          # a tall scroll capture pinned to fit the screen


class PinWindow(QWidget):
    closed = Signal(object)
    copyRequested = Signal(object)
    saveRequested = Signal(object)
    managerRequested = Signal(object)

    def __init__(self, image, pos: QPoint, dpr: float = 1.0):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.image = image
        self.dpr = dpr
        self.pixmap = bgr_to_pixmap(image, dpr)
        self.zoom = 1.0
        self._drag: QPoint | None = None
        self._focus_requested = False
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Esc·✕·더블클릭: 닫기 · 드래그: 이동 · 휠: 확대/축소 · Ctrl+휠: 투명도 · "
                        "Ctrl+C 복사 · Ctrl+S 저장 · 우클릭: 메뉴")
        # small bar shown on hover: opacity, size, copy, close (only ✕ when the pin is tiny)
        self.hover_bar = QWidget(self)
        self.hover_bar.setStyleSheet("QWidget { background: rgba(15,18,24,215); border-radius: 8px; }"
                                     "QToolButton { background: transparent; color: #FFFFFF; border: none; "
                                     "border-radius: 6px; font-size: 11px; padding: 0 4px; }"
                                     "QToolButton:hover { background: rgba(255,255,255,40); }")
        row = QHBoxLayout(self.hover_bar)
        row.setContentsMargins(3, 2, 3, 2)
        row.setSpacing(1)
        self.bar_buttons: dict[str, QToolButton] = {}
        for key, text, tip, fn in [("fade", "50%", "반투명 / 다시 또렷하게", self.toggle_fade),
                                   ("bigger", "+", "크게", lambda: self.zoom_by(1)),
                                   ("smaller", "−", "작게", lambda: self.zoom_by(-1)),
                                   ("copy", "복사", "복사 (Ctrl+C)", lambda: self.copyRequested.emit(self)),
                                   ("close", "", "닫기 (Esc)", self.close)]:
            b = QToolButton(self.hover_bar)
            if key == "close":
                b.setIcon(icons.icon("close", "#FFFFFF"))
                b.setIconSize(QSize(12, 12))
            else:
                b.setText(text)
            b.setToolTip(tip)
            b.setFixedHeight(22)
            b.setCursor(Qt.ArrowCursor)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.bar_buttons[key] = b
        self.close_button = self.bar_buttons["close"]
        self.hover_bar.hide()
        self._resize()
        self.move(pos)

    @property
    def image_size(self) -> tuple[int, int]:
        return self.image.shape[1], self.image.shape[0]

    def _resize(self) -> None:
        w, h = self.image_size
        self.resize(max(8, round(w / self.dpr * self.zoom)), max(8, round(h / self.dpr * self.zoom)))
        self._place_bar()

    def _place_bar(self) -> None:
        full = self.width() >= 170
        for k, b in self.bar_buttons.items():
            b.setVisible(full or k == "close")
        self.hover_bar.adjustSize()
        self.hover_bar.move(max(0, self.width() - self.hover_bar.width() - 4), 4)

    def toggle_fade(self) -> None:
        self.setWindowOpacity(1.0 if self.windowOpacity() < 0.99 else 0.5)
        self.bar_buttons["fade"].setText("100%" if self.windowOpacity() < 0.99 else "50%")

    def zoom_by(self, steps: int) -> None:
        self.zoom = min(4.0, max(MIN_ZOOM, self.zoom * (1.1 ** steps)))
        self._resize()
        self.update()

    def reset_zoom(self) -> None:
        self.zoom = 1.0
        self._resize()
        self.update()

    def opacity_by(self, steps: int) -> None:
        self.setWindowOpacity(min(1.0, max(0.2, self.windowOpacity() + 0.1 * steps)))

    # --- focus & hover -------------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._focus_requested = True

    def enterEvent(self, e):
        self._place_bar()
        self.hover_bar.show()
        self.hover_bar.raise_()

    def leaveEvent(self, e):
        self.hover_bar.hide()

    # --- painting --------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(self.rect(), self.pixmap)
        p.setPen(QPen(QColor("#1F5FD1"), 2))
        p.drawRect(QRect(0, 0, self.width() - 1, self.height() - 1))
        p.end()

    # --- mouse -----------------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if not self.hover_bar.isVisible():
            self._place_bar()
            self.hover_bar.show()
            self.hover_bar.raise_()
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
        else:
            self._drag = None  # never keep following the mouse after a lost release

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

    # --- keyboard ----------------------------------------------------------------------
    def keyPressEvent(self, e):
        k, ctrl = e.key(), bool(e.modifiers() & Qt.ControlModifier)
        if k == Qt.Key_Escape:
            self.close()
        elif ctrl and k == Qt.Key_C:
            self.copyRequested.emit(self)
        elif ctrl and k == Qt.Key_S:
            self.saveRequested.emit(self)
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1)
        elif k == Qt.Key_Minus:
            self.zoom_by(-1)
        elif k == Qt.Key_0:
            self.reset_zoom()
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        for label, fn in [("복사 (Ctrl+C)", lambda: self.copyRequested.emit(self)),
                          ("저장 (Ctrl+S)", lambda: self.saveRequested.emit(self)),
                          ("원래 크기 (0)", self.reset_zoom),
                          ("반투명 / 또렷하게", self.toggle_fade),
                          ("고정 관리…", lambda: self.managerRequested.emit(self)),
                          ("닫기 (Esc)", self.close)]:
            a = QAction(label, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(e.globalPos())

    def closeEvent(self, e):
        self.closed.emit(self)
        super().closeEvent(e)
