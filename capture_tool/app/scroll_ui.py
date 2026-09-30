"""Scroll capture windows: the small "scrolling…" box and the result window."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .render import bgr_to_pixmap

BOX_STYLE = ("QWidget#box { background: rgba(15,18,24,225); border-radius: 10px; }"
             "QLabel { color: #FFFFFF; font-size: 13px; }"
             "QPushButton { background: #E03131; color: #FFFFFF; border: none; border-radius: 6px;"
             " padding: 4px 12px; }")


class ScrollIndicator(QWidget):
    """Progress box shown next to the scrolling area. It is excluded from screenshots, so even
    when it overlaps the area it never ends up in the result."""
    stopRequested = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setObjectName("box")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(BOX_STYLE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 8)
        self.label = QLabel("스크롤 캡처 준비 중…")
        lay.addWidget(self.label)
        self.stop_button = QPushButton("중지 (Esc)")
        self.stop_button.setFocusPolicy(Qt.NoFocus)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        lay.addWidget(self.stop_button)
        self.adjustSize()

    def show_progress(self, steps: int, height: int) -> None:
        self.label.setText(f"스크롤 캡처 중… {steps}번 스크롤 · 높이 {height:,}px")
        self.adjustSize()


class ScrollResult(QWidget):
    """Shows the finished (tall) capture scaled to fit, with copy / save / PowerPoint."""
    action = Signal(str)

    def __init__(self, image, dpr: float = 1.0, title: str = "스크롤 캡처"):
        super().__init__(None, Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.image = image
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        h, w = image.shape[:2]
        info = QLabel(f"{w} × {h:,} px · 클립보드에 복사했습니다. 원하는 곳에 Ctrl+V")
        v.addWidget(info)
        area = QScrollArea()
        area.setWidgetResizable(False)
        pic = QLabel()
        pm = bgr_to_pixmap(image, dpr)
        scale = min(1.0, 460 / max(1.0, w / dpr))            # fit the width, scroll the height
        if scale < 1.0:
            pm = pm.scaledToWidth(max(1, round(pm.width() * scale)), Qt.SmoothTransformation)
        pic.setPixmap(pm)
        area.setWidget(pic)
        area.setMinimumSize(min(480, pm.width() + 24), 420)
        v.addWidget(area, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for name, label in [("copy", "다시 복사"), ("save_as", "저장…"), ("ppt", "PPT로"), ("pin", "고정"),
                            ("link_file", "파일 링크"), ("link_web", "인터넷 링크"), ("close", "닫기 (Esc)")]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name: self.trigger(n))
            row.addWidget(b)
            self.buttons[name] = b
        v.addLayout(row)
        self.resize(min(520, pm.width() + 44), min(680, pm.height() + 110))

    def trigger(self, name: str) -> None:
        if name == "close":
            self.close()
        else:
            self.action.emit(name)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def place_near(self, pos: QPoint) -> None:
        self.move(pos)
