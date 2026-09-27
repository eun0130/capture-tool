"""Quick-action icons floating next to the captured region: copy, save as, OCR, send to PowerPoint, pin."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from . import icons

ACTIONS = [
    ("copy", "copy", "복사", "클립보드에 복사 (Enter)"),
    ("save_as", "save_as", "저장", "저장 위치를 골라 저장 (Ctrl+Shift+S)"),
    ("text", "ocr", "텍스트", "이미지 속 글자를 인식해 복사"),
    ("ppt", "ppt", "PPT로", "PowerPoint를 열어 도형으로 붙여넣기"),
    ("pin", "pin", "고정", "캡처를 다른 모든 창 위에 계속 떠 있게 붙여 둡니다 — 자료를 보며 작업할 때 (F3)"),
]

STYLE = """
QWidget#sidebar { background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 14px; }
QToolButton { border: none; border-radius: 10px; color: #343A40; font-size: 11px; padding: 4px 0 2px 0; }
QToolButton:hover { background: #E6EEFB; color: #1F5FD1; }
QToolButton#primary { background: #1F5FD1; color: #FFFFFF; }
QToolButton#primary:hover { background: #174AA6; }
"""


class SideBar(QWidget):
    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        self.buttons: dict[str, QToolButton] = {}
        for name, icon_name, label, tip in ACTIONS:
            b = QToolButton(self)
            primary = name == "copy"
            b.setObjectName("primary" if primary else "")
            b.setIcon(icons.icon(icon_name, "#FFFFFF" if primary else "#343A40"))
            b.setIconSize(QSize(22, 22))
            b.setText(label)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setFixedSize(QSize(56, 54))
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            v.addWidget(b)
            self.buttons[name] = b
        self.adjustSize()

    def trigger(self, name: str) -> None:
        self.action.emit(name)
