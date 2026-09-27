"""Floating toolbar shown right under the selection, and its color/thickness palette popup."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QColorDialog, QFontComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core.annotations import DEFAULT_FONT, FONT_MAX, FONT_MIN, MAX_WIDTH
from . import icons

TOOLS = [
    ("select", "선택/이동 (V) · 선택 후 색·두께·서식 변경, Delete 삭제"), ("rect", "사각형 (R)"),
    ("ellipse", "타원 (O)"), ("line", "직선 (L)"), ("arrow", "화살표 (A)"), ("curve", "곡선 (C)"),
    ("pen", "펜 (P)"), ("text", "텍스트 (T)"), ("step", "번호 스탬프 (N)"), ("highlight", "형광펜 (H)"),
    ("mosaic", "모자이크 (M)"),
]
PALETTE = ["#E03131", "#F76707", "#FAB005", "#40C057", "#12B886", "#228BE6", "#4C6EF5", "#7950F2",
           "#E64980", "#862E9C", "#5C940D", "#0B7285", "#000000", "#495057", "#ADB5BD", "#FFFFFF"]
WIDTH_PRESETS = [1, 2, 4, 6, 10, 20]
TEXT_STYLES = [("bold", "B", "굵게 (Ctrl+B)"), ("italic", "I", "기울임 (Ctrl+I)"),
               ("underline", "U", "밑줄 (Ctrl+U)"), ("strike", "S", "취소선 (Ctrl+5)")]
DEFAULT_FONT_SIZE = 22
FONT_STEP = 2

STYLE = """
QWidget#toolbar { background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 12px; }
QToolButton { border: none; border-radius: 8px; padding: 0; background: transparent; color: #343A40; }
QToolButton:hover { background: #F1F3F5; }
QToolButton:checked { background: #E6EEFB; color: #1F5FD1; }
QSpinBox { min-height: 30px; padding: 0 4px; border: 1px solid #D9DCE1; border-radius: 6px; }
"""


class Toolbar(QWidget):
    toolChanged = Signal(str)
    action = Signal(str)          # text, shapes, undo, redo, cancel
    styleChanged = Signal(str)    # which attribute changed: color, width, fill, opacity, font_size, bold, ...

    def __init__(self, parent=None, tool="rect", color="#E03131", width=4, recent=None,
                 font_family=DEFAULT_FONT):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.color, self.line_width, self.fill, self.opacity = color, width, False, 1.0
        self.default_font_size = DEFAULT_FONT_SIZE
        self.font_size = DEFAULT_FONT_SIZE
        self.bold = self.italic = self.underline = self.strike = False
        self.font_family = font_family or DEFAULT_FONT
        self.recent = list(recent or [])
        self.buttons: dict[str, QWidget] = {}
        self._items: list[QWidget] = []
        self._text_items: set[int] = set()
        self._text_visible = False
        self._split = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(4)
        for name, tip in TOOLS:
            b = self._tool_button(name, tip, checkable=True)
            b.clicked.connect(lambda _=False, n=name: self.set_tool(n))
            self.addWidget(b)
        self.addWidget(self._sep())
        self.color_btn = QToolButton()
        self.color_btn.setToolTip("색상 · 두께 · 투명도  ([ ] 두께 조절)")
        self.color_btn.setFixedSize(QSize(44, 40))
        self.color_btn.clicked.connect(self.open_palette)
        self.addWidget(self.color_btn)
        fill = self._tool_button("fill", "채우기", checkable=True)
        fill.toggled.connect(self._set_fill)
        self.addWidget(fill)
        # text style group (shown for the text tool / a selected text)
        self.font_combo = QFontComboBox()
        self.font_combo.setToolTip("글씨체 — 목록에서 고르거나 이름을 입력하세요")
        self.font_combo.setMaximumWidth(170)
        self.font_combo.setFocusPolicy(Qt.ClickFocus)
        self.font_combo.setCurrentFont(QFont(self.font_family))
        self.font_combo.currentFontChanged.connect(self._font_combo_changed)
        self.buttons["font_family"] = self.font_combo
        self._add_text_item(self.font_combo)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(FONT_MIN, FONT_MAX)
        self.font_spin.setValue(self.font_size)
        self.font_spin.setSuffix(" px")
        self.font_spin.setToolTip("글자 크기 (Ctrl+] 크게 · Ctrl+[ 작게)")
        self.font_spin.setFocusPolicy(Qt.ClickFocus)
        self.font_spin.valueChanged.connect(self._font_spin_changed)
        self.buttons["font_size"] = self.font_spin
        self._add_text_item(self.font_spin)
        for name, label, tip in TEXT_STYLES:
            b = QToolButton()
            b.setText(label)
            f = QFont()
            f.setPixelSize(15)
            f.setBold(name == "bold")
            f.setItalic(name == "italic")
            f.setUnderline(name == "underline")
            f.setStrikeOut(name == "strike")
            b.setFont(f)
            b.setFixedSize(QSize(32, 38))
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda on, n=name: self._set_style(n, on))
            self.buttons[name] = b
            self._add_text_item(b)
        self._split = len(self._items)
        self.addWidget(self._sep())
        # copy / save / OCR / PowerPoint / pin live in the side bar next to the capture
        for name, tip in [("undo", "되돌리기 (Ctrl+Z)"), ("redo", "다시 실행 (Ctrl+Y)")]:
            b = self._tool_button(name, tip)
            b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            self.addWidget(b)
        close = self._tool_button("close", "취소 (Esc)")
        close.clicked.connect(lambda: self.action.emit("cancel"))
        self.addWidget(close)
        self.palette = PalettePopup(self)
        self.set_tool(tool)
        self._refresh_color()
        self.arrange(10_000)

    # --- layout -------------------------------------------------------------------------
    def addWidget(self, w: QWidget) -> None:
        # parent right away: showing a parentless widget would create a native top-level window
        w.setParent(self)
        self._items.append(w)

    def _add_text_item(self, w: QWidget) -> None:
        self._text_items.add(len(self._items))
        self.addWidget(w)

    def show_text_style(self, on: bool) -> None:
        if on != self._text_visible:
            self._text_visible = on
            self.arrange(self._last_width if hasattr(self, "_last_width") else 10_000)

    def arrange(self, max_width: int) -> None:
        """One row if it fits, otherwise drawing tools on row 1 and the rest on row 2."""
        self._last_width = max_width
        for w in self._items:
            self._grid.removeWidget(w)
        visible = [(i, w) for i, w in enumerate(self._items) if self._text_visible or i not in self._text_items]
        for i, w in enumerate(self._items):
            if not (self._text_visible or i not in self._text_items):
                w.hide()
        one_row = sum(w.sizeHint().width() for _, w in visible) + 2 * len(visible) + 12
        split = len(self._items) if one_row <= max_width else self._split
        col = {0: 0, 1: 0}
        for i, w in visible:
            row = 0 if i < split else 1
            if row == 1 and col[1] == 0 and isinstance(w, QFrame) and not isinstance(w, QToolButton):
                w.hide()
                continue
            w.show()
            self._grid.addWidget(w, row, col[row])
            col[row] += 1
        self._grid.setColumnStretch(len(self._items), 1)
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

    # --- actions & tools -------------------------------------------------------------------
    def trigger(self, name: str) -> None:
        """Programmatic click (tests, keyboard shortcuts)."""
        self.action.emit(name)

    def set_tool(self, name: str) -> None:
        self.tool = name
        for n, _ in TOOLS:
            self.buttons[n].setChecked(n == name)
        self.show_text_style(name == "text")
        self.toolChanged.emit(name)

    # --- style -------------------------------------------------------------------------------
    def _set_fill(self, on: bool) -> None:
        self.fill = on
        self.styleChanged.emit("fill")

    def set_color(self, color: str) -> None:
        self.color = color
        if color in self.recent:
            self.recent.remove(color)
        self.recent = ([color] + self.recent)[:8]
        self._refresh_color()
        self.styleChanged.emit("color")

    def set_width(self, w: float) -> None:
        w = round(min(MAX_WIDTH, max(1, w)))
        self.line_width = w
        self.palette.sync_width(w)
        self.styleChanged.emit("width")

    def bump_width(self, delta: int) -> None:
        self.set_width(self.line_width + delta)

    def set_opacity(self, o: float) -> None:
        self.opacity = o
        self.styleChanged.emit("opacity")

    def _font_combo_changed(self, font: QFont) -> None:
        fam = font.family()
        if fam and fam != self.font_family:
            self.font_family = fam
            self.styleChanged.emit("font_family")

    def set_font_family(self, family: str) -> None:
        self.font_family = family or DEFAULT_FONT
        self.font_combo.blockSignals(True)
        self.font_combo.setCurrentFont(QFont(self.font_family))
        self.font_combo.blockSignals(False)
        self.styleChanged.emit("font_family")

    def _font_spin_changed(self, v: int) -> None:
        if v != self.font_size:
            self.font_size = v
            self.styleChanged.emit("font_size")

    def set_font_size(self, v: int) -> None:
        v = int(min(FONT_MAX, max(FONT_MIN, v)))
        self.font_size = v
        self.font_spin.blockSignals(True)
        self.font_spin.setValue(v)
        self.font_spin.blockSignals(False)
        self.styleChanged.emit("font_size")

    def bump_font(self, steps: int) -> None:
        self.set_font_size(self.font_size + steps * FONT_STEP)

    def _set_style(self, name: str, on: bool) -> None:
        setattr(self, name, on)
        self.buttons[name].setChecked(on)
        self.styleChanged.emit(name)

    def toggle_style(self, name: str) -> None:
        self._set_style(name, not getattr(self, name))

    def load_text_style(self, shape) -> None:
        """Show a selected text's style in the controls without re-applying it."""
        self.blockSignals(True)
        self.set_font_size(shape.font_size)
        self.set_font_family(shape.font_family)
        for name, _, _ in TEXT_STYLES:
            setattr(self, name, getattr(shape, name))
            self.buttons[name].setChecked(getattr(shape, name))
        self.blockSignals(False)

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
        # thickness: any value 1..60 px (slider + number), plus quick presets
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("두께"))
        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(1, MAX_WIDTH)
        self.width_slider.setValue(int(bar.line_width))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, MAX_WIDTH)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(int(bar.line_width))
        self.width_slider.valueChanged.connect(self._width_from_ui)
        self.width_spin.valueChanged.connect(self._width_from_ui)
        wrow.addWidget(self.width_slider, 1)
        wrow.addWidget(self.width_spin)
        v.addLayout(wrow)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("빠른 선택"))
        for w in WIDTH_PRESETS:
            b = QPushButton(f"{w}")
            b.setFixedWidth(34)
            b.clicked.connect(lambda _=False, w=w: self.bar.set_width(w))
            prow.addWidget(b)
        v.addLayout(prow)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("투명도"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(10, 100)
        self.slider.setValue(100)
        self.slider.valueChanged.connect(lambda v: self.bar.set_opacity(v / 100))
        orow.addWidget(self.slider)
        v.addLayout(orow)

    def _width_from_ui(self, v: int) -> None:
        if v != self.bar.line_width:
            self.bar.set_width(v)

    def sync_width(self, w: int) -> None:
        for ctl in (self.width_slider, self.width_spin):
            ctl.blockSignals(True)
            ctl.setValue(int(w))
            ctl.blockSignals(False)

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
