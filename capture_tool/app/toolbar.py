"""Floating toolbar shown right under the selection, and its color/thickness palette popup."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (QColorDialog, QComboBox, QCompleter, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core.annotations import DEFAULT_FONT, FONT_MAX, FONT_MIN, MAX_WIDTH
from ..core.fonts import SEPARATOR, build_font_list
from . import icons

TOOLS = [
    ("select", "선택/이동 (V) · 선택 후 색·두께·서식 변경, Delete 삭제"), ("rect", "사각형 (R)"),
    ("ellipse", "타원 (O)"), ("line", "직선 (L)"), ("arrow", "화살표 (A)"), ("curve", "곡선 (C)"),
    ("pen", "펜 (P)"), ("text", "텍스트 (T)"), ("step", "번호 스탬프 (N)"), ("highlight", "형광펜 (H)"),
    ("mosaic", "모자이크 (M)"), ("crop", "자르기 (X) · 남길 부분을 네모로 끌면 그 크기로 잘립니다 (Ctrl+Z 되돌리기)"),
    ("lasso", "자유형 자르기 (K) · 남길 부분을 따라 그리면 그 모양으로 잘립니다"),
]
PALETTE = ["#E03131", "#F76707", "#FAB005", "#40C057", "#12B886", "#228BE6", "#4C6EF5", "#7950F2",
           "#E64980", "#862E9C", "#5C940D", "#0B7285", "#000000", "#495057", "#ADB5BD", "#FFFFFF"]
WIDTH_PRESETS = [1, 2, 4, 6, 10, 20]
# highlighter inks: yellow, green, pink, sky, orange, violet
HIGHLIGHT_COLORS = ["#FFE066", "#8CE99A", "#F783AC", "#74C0FC", "#FFC078", "#B197FC"]
HIGHLIGHT_NAMES = ["노랑", "연두", "분홍", "하늘", "주황", "보라"]
# text background: light tints first (readable under dark text), then the drawing palette
TEXT_BG_COLORS = ["#FFEC99", "#D3F9D8", "#D0EBFF", "#FFDEEB", "#F1F3F5", "#FFFFFF"] + PALETTE[:10] + ["#000000", "#495057"]
TEXT_STYLES = [("bold", "B", "굵게 (Ctrl+B)"), ("italic", "I", "기울임 (Ctrl+I)"),
               ("underline", "U", "밑줄 (Ctrl+U)"), ("strike", "S", "취소선 (Ctrl+5)")]
DEFAULT_FONT_SIZE = 22
FONT_STEP = 2

INK = "#E9ECF2"                  # icons on the dark bar (same look as the action bar)

STYLE = """
QWidget#toolbar { background: #1B1F2A; border: 1px solid #353C4E; border-radius: 14px; }
QToolButton { border: none; border-radius: 9px; padding: 0; background: transparent; color: #E9ECF2; }
QToolButton:hover { background: #2D3446; }
QToolButton:checked { background: #20365E; color: #8FB6FF; }
QSpinBox { min-height: 30px; padding: 0 4px; border: 1px solid #353C4E; border-radius: 6px;
           background: #262C3A; color: #E9ECF2; }
QLabel { color: #C9CFDB; }
"""


class Toolbar(QWidget):
    toolChanged = Signal(str)
    action = Signal(str)          # text, shapes, undo, redo, cancel
    styleChanged = Signal(str)    # which attribute changed: color, width, fill, opacity, font_size, bold, ...
    symbolChosen = Signal(str)

    def __init__(self, parent=None, tool="rect", color="#E03131", width=4, recent=None,
                 font_family=DEFAULT_FONT, highlight_color=None, text_bg=None):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.color, self.line_width, self.fill, self.opacity = color, width, False, 1.0
        self.default_font_size = DEFAULT_FONT_SIZE
        self.font_size = DEFAULT_FONT_SIZE
        self.bold = self.italic = self.underline = self.strike = False
        self.font_family = font_family or DEFAULT_FONT
        self.highlight_color = highlight_color or HIGHLIGHT_COLORS[0]
        self.bg = text_bg
        self.tool = tool
        self.recent = list(recent or [])
        self.buttons: dict[str, QWidget] = {}
        self._items: list[QWidget] = []
        self._group_of: dict[int, str] = {}     # item index -> "text" / "highlight" (shown on demand)
        self._shown: set[str] = set()
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
        self.font_combo = FontPicker()
        self.font_combo.select_family(self.font_family)
        self.font_combo.familyChosen.connect(self._font_combo_changed)
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
        self.bg_btn = QToolButton()
        self.bg_btn.setText("배경")
        self.bg_btn.setFixedSize(QSize(44, 38))
        self.bg_btn.setToolTip("글자 배경색")
        self.bg_btn.setFocusPolicy(Qt.NoFocus)
        self.bg_btn.clicked.connect(self.open_bg_palette)
        self.buttons["bg"] = self.bg_btn
        self._add_text_item(self.bg_btn)
        sym = QToolButton()
        sym.setText("※")
        f = QFont()
        f.setPixelSize(17)
        sym.setFont(f)
        sym.setFixedSize(QSize(34, 38))
        sym.setToolTip("기호 넣기 (★ ✓ → ① ※ …)")
        sym.setFocusPolicy(Qt.NoFocus)
        sym.clicked.connect(self.open_symbols)
        self.buttons["symbol"] = sym
        self._add_text_item(sym)
        for i, (c, n) in enumerate(zip(HIGHLIGHT_COLORS, HIGHLIGHT_NAMES)):
            b = QToolButton()
            b.setFixedSize(QSize(28, 38))
            b.setCheckable(True)
            b.setToolTip(f"형광펜 {n}")
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(f"QToolButton {{ background: {c}; border-radius: 6px; margin: 7px 2px; }}"
                            f"QToolButton:checked {{ border: 2px solid #343A40; }}")
            b.clicked.connect(lambda _=False, c=c: self.set_highlight_color(c))
            self.buttons[f"hl_{i}"] = b
            self._add_group_item(b, "highlight")
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
        self.bg_palette = BgPopup(self)
        self.symbols = SymbolPopup(self)
        self.set_tool(tool)
        self._refresh_color()
        self._refresh_bg()
        self.arrange(10_000)

    # --- layout -------------------------------------------------------------------------
    def addWidget(self, w: QWidget) -> None:
        # parent right away: showing a parentless widget would create a native top-level window
        w.setParent(self)
        self._items.append(w)

    def _add_group_item(self, w: QWidget, group: str) -> None:
        self._group_of[len(self._items)] = group
        self.addWidget(w)

    def _add_text_item(self, w: QWidget) -> None:
        self._add_group_item(w, "text")

    def _show_group(self, group: str, on: bool) -> None:
        if on != (group in self._shown):
            self._shown.symmetric_difference_update({group})
            self.arrange(self._last_width if hasattr(self, "_last_width") else 10_000)

    def show_text_style(self, on: bool) -> None:
        self._show_group("text", on)

    def _visible(self, i: int) -> bool:
        g = self._group_of.get(i)
        return g is None or g in self._shown

    def arrange(self, max_width: int) -> None:
        """One row if it fits, otherwise drawing tools on row 1 and the rest on row 2."""
        self._last_width = max_width
        for w in self._items:
            self._grid.removeWidget(w)
        visible = [(i, w) for i, w in enumerate(self._items) if self._visible(i)]
        for i, w in enumerate(self._items):
            if not self._visible(i):
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
        b.setIcon(icons.icon(name, INK))
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
        f.setStyleSheet("background:#353C4E; margin: 0 6px;")
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
        self._show_group("highlight", name == "highlight")
        self._refresh_color()
        self.toolChanged.emit(name)

    # --- style -------------------------------------------------------------------------------
    def _set_fill(self, on: bool) -> None:
        self.fill = on
        self.styleChanged.emit("fill")

    def set_color(self, color: str) -> None:
        if self.tool == "highlight":   # the palette picks the highlighter's ink while it is active
            self.set_highlight_color(color)
            return
        self.color = color
        if color in self.recent:
            self.recent.remove(color)
        self.recent = ([color] + self.recent)[:8]
        self._refresh_color()
        self.styleChanged.emit("color")

    def set_highlight_color(self, color: str) -> None:
        self.highlight_color = color
        self._refresh_color()
        self.styleChanged.emit("highlight_color")

    def set_bg(self, color: str | None) -> None:
        self.bg = color or None
        self._refresh_bg()
        self.styleChanged.emit("bg")

    def choose_symbol(self, ch: str) -> None:
        self.symbols.hide()
        self.symbolChosen.emit(ch)

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

    def _font_combo_changed(self, fam: str) -> None:
        if fam and fam != self.font_family:
            self.font_family = fam
            self.styleChanged.emit("font_family")

    def set_font_family(self, family: str) -> None:
        self.font_family = family or DEFAULT_FONT
        self.font_combo.blockSignals(True)
        self.font_combo.select_family(self.font_family)
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
        self.bg = shape.bg
        self._refresh_bg()
        for name, _, _ in TEXT_STYLES:
            setattr(self, name, getattr(shape, name))
            self.buttons[name].setChecked(getattr(shape, name))
        self.blockSignals(False)

    def _refresh_color(self) -> None:
        if not hasattr(self, "color_btn"):
            return
        c = self.highlight_color if self.tool == "highlight" else self.color
        self.color_btn.setStyleSheet(
            f"QToolButton {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,"
            f" stop:0 {c}, stop:0.49 {c}, stop:0.5 transparent); border-radius: 8px; }}")
        for i, hc in enumerate(HIGHLIGHT_COLORS):
            b = self.buttons.get(f"hl_{i}")
            if b is not None:
                b.setChecked(hc == self.highlight_color)

    def _refresh_bg(self) -> None:
        if self.bg:
            self.bg_btn.setStyleSheet(f"QToolButton {{ background: {self.bg}; border: 1px solid #ADB5BD;"
                                      " border-radius: 6px; margin: 5px 1px; color: #212529; }")
        else:
            self.bg_btn.setStyleSheet("")

    def _popup_under(self, popup: QWidget, anchor: QWidget) -> None:
        popup.adjustSize()
        popup.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 6)))
        popup.show()

    def open_bg_palette(self) -> None:
        self._popup_under(self.bg_palette, self.bg_btn)

    def open_symbols(self) -> None:
        self._popup_under(self.symbols, self.buttons["symbol"])

    def open_palette(self) -> None:
        self.palette.refresh()
        self.palette.adjustSize()
        pos = self.color_btn.mapToGlobal(QPoint(0, self.color_btn.height() + 6))
        self.palette.move(pos)
        self.palette.show()


class FontPicker(QComboBox):
    """Font box: popular Korean fonts (installed ones) on top, a separator, then every other
    font A→Z. Type a name to jump to it."""
    familyChosen = Signal(str)

    def __init__(self, families: list[str] | None = None):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(18)
        self.setMaximumWidth(180)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setToolTip("글씨체 — 위쪽은 자주 쓰는 한글 글꼴, 아래는 모든 글꼴. 이름을 입력해도 됩니다")
        fams = families if families is not None else QFontDatabase.families()
        for label, fam in build_font_list(fams):
            if (label, fam) == SEPARATOR:
                self.insertSeparator(self.count())
                continue
            self.addItem(label, fam)
            if label != fam:  # show popular fonts in their own typeface
                self.setItemData(self.count() - 1, QFont(fam), Qt.FontRole)
        comp = QCompleter(self.model(), self)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompleter(comp)
        self.currentIndexChanged.connect(self._index_changed)
        self.lineEdit().editingFinished.connect(self._typed)

    def _index_changed(self, i: int) -> None:
        fam = self.itemData(i)
        if fam:
            self.familyChosen.emit(fam)

    def _typed(self) -> None:
        text = self.currentText().strip().casefold()
        for i in range(self.count()):
            if self.itemData(i) and text in (self.itemText(i).casefold(), str(self.itemData(i)).casefold()):
                if i != self.currentIndex():
                    self.setCurrentIndex(i)
                return

    def select_family(self, family: str) -> None:
        i = self.findData(family)
        if i < 0:
            i = self.findText(family)
        if i >= 0:
            self.setCurrentIndex(i)
        else:
            self.setEditText(family)   # saved font not installed here: keep the name


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


class _Popup(QFrame):
    def __init__(self, bar: Toolbar):
        super().__init__(bar, Qt.Popup)
        self.bar = bar
        self.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 12px; }"
                           "QLabel { border: none; color: #5B616B; font-size: 12px; }"
                           "QToolButton { border: none; border-radius: 6px; font-size: 17px;"
                           " font-family: \"Malgun Gothic\"; }"
                           "QToolButton:hover { background: #E6EEFB; }")


class BgPopup(_Popup):
    """Text background: none, light tints, palette colors."""

    def __init__(self, bar: Toolbar):
        super().__init__(bar)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        none = QPushButton("배경 없음")
        none.clicked.connect(lambda: (self.bar.set_bg(None), self.hide()))
        v.addWidget(none)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, c in enumerate(TEXT_BG_COLORS):
            b = QPushButton()
            b.setFixedSize(24, 24)
            b.setToolTip(c)
            b.setStyleSheet(f"QPushButton {{ background: {c}; border: 1px solid rgba(0,0,0,0.25); border-radius: 4px; }}")
            b.clicked.connect(lambda _=False, c=c: (self.bar.set_bg(c), self.hide()))
            grid.addWidget(b, i // 6, i % 6)
        v.addLayout(grid)


class SymbolPopup(_Popup):
    """Grid of symbols by group; a click puts the symbol into the text."""

    def __init__(self, bar: Toolbar):
        super().__init__(bar)
        from ..core.symbols import SYMBOLS
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(4)
        for name, chars in SYMBOLS:
            v.addWidget(QLabel(name))
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, ch in enumerate(chars):
                b = QToolButton()
                b.setText(ch)
                b.setFont(QFont(DEFAULT_FONT))   # show the glyph the text will actually use
                b.setFixedSize(QSize(30, 30))
                b.setFocusPolicy(Qt.NoFocus)
                b.clicked.connect(lambda _=False, ch=ch: self.bar.choose_symbol(ch))
                grid.addWidget(b, i // 12, i % 12)
            v.addLayout(grid)
