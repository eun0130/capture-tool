"""Edit window for captures bigger than a screen (scroll capture, a window across monitors): the
same canvas, drawing toolbar and side bar as a normal capture, in a resizable window with zoom."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.geometry import Monitor, Rect
from .overlay import OverlayWindow

ZOOMS = [0.25, 0.33, 0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
HINT = ("그리기·텍스트(글자 인식)·PPT로·도형PPT·링크·고정 모두 쓸 수 있습니다 · "
        "Ctrl+휠 확대/축소 · 휠 위아래 이동 · Enter 복사 · Esc 닫기")


class EditorWindow(QWidget):
    def __init__(self, controller, image, title: str, dpr: float | None = None):
        super().__init__(None, Qt.Window)
        self.c = controller
        self._closing = False
        h, w = image.shape[:2]
        scr = QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()
        self.dpr = dpr or (scr.devicePixelRatio() if scr else 1.0)
        self.setWindowTitle(f"캡처 편집 — {title} ({w} × {h:,}px)")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.hint = QLabel(HINT)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #495057;")
        v.addWidget(self.hint)
        self.top = QHBoxLayout()
        v.addLayout(self.top)
        body = QHBoxLayout()
        v.addLayout(body, 1)
        self.area = QScrollArea()
        self.area.setWidgetResizable(False)
        self.area.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.area.setStyleSheet("QScrollArea { background: #5C636A; }")
        body.addWidget(self.area, 1)
        mon = Monitor(-1, Rect(0, 0, w, h), self.dpr, False, "editor")
        self.canvas = OverlayWindow(controller, mon, image, embedded=self)
        self.area.setWidget(self.canvas)
        cv = self.canvas
        cv.side_bar.remove_action("scroll")
        self.top.addWidget(cv.toolbar)
        self.top.addWidget(cv.ocr_bar)
        self.top.addStretch(1)
        for label, fn, tip in [("축소 -", lambda: self.zoom_by(-1), "축소 (Ctrl+휠)"),
                               ("확대 +", lambda: self.zoom_by(1), "확대 (Ctrl+휠)"),
                               ("100%", lambda: self.set_zoom(1.0), "실제 크기"),
                               ("폭 맞춤", self.fit_width, "창 너비에 맞추기")]:
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            self.top.addWidget(b)
        self.zoom_label = QLabel()
        self.top.addWidget(self.zoom_label)
        body.addWidget(cv.side_bar, 0, Qt.AlignTop)
        cv.side_bar.set_columns(1)
        self.zoom = 1.0
        g = scr.availableGeometry() if scr else None
        if g is not None:
            self.resize(int(g.width() * 0.85), int(g.height() * 0.9))
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + (g.height() - self.height()) // 2)
        self._apply_zoom()

    # --- zoom ------------------------------------------------------------------------------------------
    def _apply_zoom(self) -> None:
        cv = self.canvas
        cv.close_text_editor()
        cv.scale = self.dpr / self.zoom
        cv.pixmap.setDevicePixelRatio(cv.scale)
        h, w = cv.image.shape[:2]
        cv.setFixedSize(max(1, round(w / cv.scale)), max(1, round(h / cv.scale)))
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        cv.update()

    def set_zoom(self, z: float) -> None:
        self.zoom = min(4.0, max(0.1, z))
        self._apply_zoom()

    def zoom_by(self, steps: int) -> None:
        if steps > 0:
            nxt = [z for z in ZOOMS if z > self.zoom + 1e-6]
            self.set_zoom(nxt[0] if nxt else ZOOMS[-1])
        else:
            prev = [z for z in ZOOMS if z < self.zoom - 1e-6]
            self.set_zoom(prev[-1] if prev else ZOOMS[0])

    def fit_width(self) -> None:
        w = self.canvas.image.shape[1]
        avail = max(100, self.area.viewport().width() - 4)
        self.set_zoom(avail * self.dpr / w)

    def initial_zoom(self) -> None:
        """Actual size, or narrower to fit the window width (never enlarged at first)."""
        w = self.canvas.image.shape[1]
        if w / self.dpr > self.area.viewport().width() - 4:
            self.fit_width()
        else:
            self.set_zoom(1.0)

    # --- closing ----------------------------------------------------------------------------------------
    def close_from_controller(self) -> None:
        self._closing = True
        self.close()

    def closeEvent(self, e):
        if not self._closing:
            self._closing = True
            self.c.cancel()              # same as Esc: ends the session (auto-save rules apply)
        super().closeEvent(e)
