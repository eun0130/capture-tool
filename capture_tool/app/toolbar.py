"""Floating toolbar shown right under the selection, and its color palette popup."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

from . import icons

TOOLS = [
    ("select", "선택/이동 (V)"), ("rect", "사각형 (R)"), ("ellipse", "타원 (O)"), ("line", "직선 (L)"),
    ("arrow", "화살표 (A)"), ("curve", "곡선 (C)"), ("pen", "펜 (P)"), ("text", "텍스트 (T)"),
    ("step", "번호 스탬프 (N)"), ("highlight", "형광펜 (H)"), ("mosaic", "모자이크 (M)"),
]
PALETTE = ["#E03131", "#F76707", "#FAB005", "#40C057", "#12B886", "#228BE6", "#4C6EF5", "#7950F2",
           "#E64980", "#862E9C", "#5C940D", "#0B7285", "#000000", "#495057", "#ADB5BD", "#FFFFFF"]
WIDTHS = [2, 4, 6, 10]

STYLE = """
QWidget#toolbar { background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 12px; }
QToolButton { border: none; border-radius: 8px; padding: 0; background: transparent; }
QToolButton:hover { background: #F1F3F5; }
QToolButton:checked { background: #E6EEFB; }
QPushButton#primary { background: #1F5FD1; color: white; border: none; border-radius: 8px;
    padding: 0 14px; font-weight: 600; min-height: 36px; }
QPushButton#label { background: transparent; color: #343A40; border: none; border-radius: 8px;
    padding: 0 10px; min-height: 36px; }
QPushButton#label:hover { background: #F1F3F5; }
"""


class Toolbar(QWidget):
    toolChanged = Signal(str)
    action = Signal(str)          # text, shapes, undo, redo, pin, save, copy, cancel
    styleChanged = Signal()

    def __init__(self, parent=None, tool="rect", color="#E03131", width=4, recent=None):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.color, self.width, self.fill, self.opacity = color, width, False, 1.0
        self.recent = list(recent or [])
        self.buttons: dict[str, QWidget] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(2)
        for name, tip in TOOLS:
            b = self._tool_button(name, tip, checkable=True)
            b.clicked.connect(lambda _=False, n=name: self.set_tool(n))
            lay.addWidget(b)
        lay.addWidget(self._sep())
        self.color_btn = QToolButton()
        self.color_btn.setToolTip("색상 · 두께 · 투명도")
        self.color_btn.setFixedSize(QSize(44, 40))
        self.color_btn.clicked.connect(self.open_palette)
        lay.addWidget(self.color_btn)
        fill = self._tool_button("fill", "채우기", checkable=True)
        fill.toggled.connect(self._set_fill)
        lay.addWidget(fill)
        lay.addWidget(self._sep())
        for name, label, tip in [("text", "텍스트", "이미지 속 글자 복사"), ("shapes", "도형→PPT", "도형을 PowerPoint 도형으로 복사")]:
            b = QPushButton(icons.icon("ocr" if name == "text" else "shapes"), label)
            b.setObjectName("label")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            self.buttons[f"act_{name}"] = b
            lay.addWidget(b)
        lay.addWidget(self._sep())
        for name, tip in [("undo", "되돌리기 (Ctrl+Z)"), ("redo", "다시 실행 (Ctrl+Y)"), ("pin", "화면에 고정 (F3)"),
                          ("save", "저장 (Ctrl+S)")]:
            b = self._tool_button(name, tip)
            b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            lay.addWidget(b)
        copy = QPushButton(icons.icon("copy", "#FFFFFF"), "복사")
        copy.setObjectName("primary")
        copy.setToolTip("클립보드에 복사 (Enter)")
        copy.clicked.connect(lambda: self.action.emit("copy"))
        self.buttons["copy"] = copy
        lay.addWidget(copy)
        close = self._tool_button("close", "취소 (Esc)")
        close.clicked.connect(lambda: self.action.emit("cancel"))
        lay.addWidget(close)
        self.palette = PalettePopup(self)
        self.set_tool(tool)
        self._refresh_color()
        self.adjustSize()

    def _tool_button(self, name, tip, checkable=False) -> QToolButton:
        b = QToolButton()
        b.setIcon(icons.icon(name))
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(QSize(38, 38))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.NoFocus)
        self.buttons[name] = b
        return b

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFixedSize(1, 26)
        f.setStyleSheet("background:#D9DCE1; margin: 0 6px;")
        return f

    def trigger(self, name: str) -> None:
        """Programmatic click (tests, keyboard shortcuts)."""
        self.action.emit(name)

    def set_tool(self, name: str) -> None:
        self.tool = name
        for n, _ in TOOLS:
            self.buttons[n].setChecked(n == name)
        self.toolChanged.emit(name)

    def _set_fill(self, on: bool) -> None:
        self.fill = on
        self.styleChanged.emit()

    def set_color(self, color: str) -> None:
        self.color = color
        if color in self.recent:
            self.recent.remove(color)
        self.recent = ([color] + self.recent)[:8]
        self._refresh_color()
        self.styleChanged.emit()

    def set_width(self, w: int) -> None:
        self.width = w
        self.styleChanged.emit()

    def set_opacity(self, o: float) -> None:
        self.opacity = o
        self.styleChanged.emit()

    def _refresh_color(self) -> None:
        self.color_btn.setStyleSheet(
            f"QToolButton {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,"
            f" stop:0 {self.color}, stop:0.49 {self.color}, stop:0.5 transparent); border-radius: 8px; }}")

    def open_palette(self) -> None:
        self.palette.refresh()
        self.palette.adjustSize()
        pos = self.color_btn.mapToGlobal(QPoint(0, self.color_btn.height() + 6))
        self.palette.move(pos)
        self.palette.show()


class PalettePopup(QFrame):
    def __init__(self, bar: Toolbar):
        super().__init__(bar, Qt.Popup)
        self.bar = bar
        self.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 12px; }"
                           "QLabel { border: none; color: #5B616B; font-size: 12px; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, c in enumerate(PALETTE):
            grid.addWidget(self._swatch(c, 26), i // 8, i % 8)
        v.addLayout(grid)
        self.recent_row = QHBoxLayout()
        v.addLayout(self.recent_row)
        custom = QPushButton("사용자 지정 색…")
        custom.clicked.connect(self._custom)
        v.addWidget(custom)
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("두께"))
        for w in WIDTHS:
            b = QPushButton(f"{w}px")
            b.clicked.connect(lambda _=False, w=w: self.bar.set_width(w))
            wrow.addWidget(b)
        v.addLayout(wrow)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("투명도"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(10, 100)
        self.slider.setValue(100)
        self.slider.valueChanged.connect(lambda v: self.bar.set_opacity(v / 100))
        orow.addWidget(self.slider)
        v.addLayout(orow)

    def _swatch(self, color: str, size: int) -> QPushButton:
        b = QPushButton()
        b.setFixedSize(size, size)
        b.setToolTip(color)
        b.setStyleSheet(f"QPushButton {{ background: {color}; border: 1px solid rgba(0,0,0,0.18);"
                        f" border-radius: {size // 2}px; }}")
        b.clicked.connect(lambda _=False, c=color: (self.bar.set_color(c), self.hide()))
        return b

    def refresh(self) -> None:
        while self.recent_row.count():
            item = self.recent_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.recent_row.addWidget(QLabel("최근 사용"))
        for c in self.bar.recent[:8]:
            self.recent_row.addWidget(self._swatch(c, 20))
        self.recent_row.addStretch(1)

    def _custom(self) -> None:
        c = QColorDialog.getColor(QColor(self.bar.color), self, "색 선택")
        if c.isValid():
            self.bar.set_color(c.name().upper())
        self.hide()
