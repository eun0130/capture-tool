"""Small on-screen message ("복사했습니다", "PowerPoint에 넣었습니다" …) near the bottom of the
screen the mouse is on. Windows tray notifications are often hidden (focus assist, notification
settings), so every message is also shown here. Never takes focus, ignores the mouse, and is
kept out of screenshots."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..core.geometry import Rect, place_toast

SHOW_MS = 3200
MS_PER_CHAR = 110         # longer messages (what to do next) stay long enough to read
MAX_MS = 10000


def toast_ms(text: str) -> int:
    return int(min(MAX_MS, max(SHOW_MS, MS_PER_CHAR * len(text or ""))))


class Toast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("toast")
        self.setStyleSheet("QWidget#toast { background: rgba(20,24,31,235); border-radius: 10px; }"
                           "QLabel { color: #FFFFFF; font-size: 14px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 10)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(560)
        lay.addWidget(self.label)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._excluded = False

    def show_message(self, text: str, ms: int = SHOW_MS, avoid=()) -> None:
        """`avoid`: screen rectangles (logical px) the message must not cover - the capture
        being edited and its bars (BUG-114)."""
        self.label.setText(text)
        self.adjustSize()
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            x, y = place_toast((self.width(), self.height()), Rect(g.x(), g.y(), g.width(), g.height()), avoid)
            self.move(QPoint(x, y))
        self.show()
        self.raise_()
        if not self._excluded:
            self._excluded = True
            try:
                from .. import platform as pf
                pf.backend().scroll.exclude_from_capture(int(self.winId()))
            except (OSError, ImportError, AttributeError):
                pass
        self._timer.start(max(1500, ms))
