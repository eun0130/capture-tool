"""Small on-screen message ("복사했습니다", "PowerPoint에 넣었습니다" …) near the bottom of the
screen the mouse is on. Windows tray notifications are often hidden (focus assist, notification
settings), so every message is also shown here. Never takes focus, ignores the mouse, and is
kept out of screenshots."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

SHOW_MS = 3200


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

    def show_message(self, text: str, ms: int = SHOW_MS) -> None:
        self.label.setText(text)
        self.adjustSize()
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(QPoint(g.center().x() - self.width() // 2, g.bottom() - self.height() - 60))
        self.show()
        self.raise_()
        if not self._excluded:
            self._excluded = True
            try:
                from ..platform.scroll import exclude_from_capture
                exclude_from_capture(int(self.winId()))
            except (OSError, ImportError, AttributeError):
                pass
        self._timer.start(max(1500, ms))
