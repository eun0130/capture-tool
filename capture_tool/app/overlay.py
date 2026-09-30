"""Full-screen frozen overlay for one monitor: select a region, then draw on it in place.

Coordinates: widget-local logical px <-> global physical px (monitor origin + local * scale).
Annotations (core Document) use physical px relative to the selection."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ..core.annotations import Shape
from ..core.clip import polygon
from ..core.color import pixel_color
from ..core.geometry import Rect, layout_bars, match_screen
from ..core.session import State
from .render import FONT_FAMILY, apply_mosaic, bgr_to_pixmap, bgr_to_qimage, paint_document
from .side_bar import SideBar
from .toolbar import Toolbar

DIM = QColor(15, 18, 24, 140)
ACCENT = QColor("#4C8DFF")
TOOL_KEYS = {Qt.Key_V: "select", Qt.Key_R: "rect", Qt.Key_O: "ellipse", Qt.Key_L: "line", Qt.Key_A: "arrow",
             Qt.Key_C: "curve", Qt.Key_P: "pen", Qt.Key_T: "text", Qt.Key_N: "step", Qt.Key_H: "highlight",
             Qt.Key_M: "mosaic", Qt.Key_K: "lasso"}
BOX_TOOLS = {"rect", "ellipse", "highlight", "mosaic", "line", "arrow"}
TEXT_STYLE_KEYS = {Qt.Key_B: "bold", Qt.Key_I: "italic", Qt.Key_U: "underline", Qt.Key_5: "strike"}


class TextEditor(QLineEdit):
    """Inline text input that previews the text style and handles the style shortcuts."""

    def __init__(self, parent, toolbar, scale: float):
        super().__init__(parent)
        self.tb = toolbar
        self.scale = scale
        self.setPlaceholderText("텍스트 입력 후 Enter · Ctrl+B/I/U/5 서식 · Ctrl+]/[ 크기")
        self.apply_style()

    def apply_style(self) -> None:
        tb = self.tb
        f = QFont(tb.font_family or FONT_FAMILY)
        f.setPixelSize(max(8, round(tb.font_size / self.scale)))
        f.setBold(tb.bold)
        f.setItalic(tb.italic)
        f.setUnderline(tb.underline)
        f.setStrikeOut(tb.strike)
        self.setFont(f)
        bg = tb.bg or "rgba(255,255,255,230)"
        self.setStyleSheet(f"QLineEdit {{ background: {bg}; color: {tb.color};"
                           " border: 1px dashed #4C8DFF; }")
        self._fit()

    def keyPressEvent(self, e):
        k, ctrl = e.key(), bool(e.modifiers() & Qt.ControlModifier)
        if k in (Qt.Key_Return, Qt.Key_Enter):
            super().keyPressEvent(e)   # emits returnPressed -> the text is added
            e.accept()                 # ...and Enter must NOT reach the capture (it would copy & close)
            return
        if k == Qt.Key_Escape:
            self.clear()               # cancel just this text, keep the capture
            self.clearFocus()
            e.accept()
            return
        if ctrl and k in TEXT_STYLE_KEYS:
            self.tb.toggle_style(TEXT_STYLE_KEYS[k])
        elif ctrl and k in (Qt.Key_BracketRight, Qt.Key_BracketLeft):
            self.tb.bump_font(1 if k == Qt.Key_BracketRight else -1)
        else:
            super().keyPressEvent(e)
            self._fit()
            return
        e.accept()
        self.apply_style()

    def _fit(self) -> None:
        fm = self.fontMetrics()
        self.resize(max(220, fm.horizontalAdvance(self.text() or self.placeholderText()[:12]) + 24), fm.height() + 12)


class OcrBar(QWidget):
    """Replaces the drawing toolbar while in text mode."""
    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("ocrbar")
        self.setStyleSheet("QWidget#ocrbar { background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 12px; }"
                           "QLabel { color: #343A40; padding: 0 6px; }"
                           "QPushButton { min-height: 34px; padding: 0 12px; border: none; border-radius: 8px;"
                           " background: #F1F3F5; color: #343A40; }"
                           "QPushButton:hover { background: #E6EEFB; color: #1F5FD1; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        lay.addWidget(QLabel("드래그한 부분의 글자를 바로 복사합니다"))
        self.buttons = {}
        for name, label in [("all", "전체 복사 (Enter)"), ("translate", "번역"), ("summarize", "요약"),
                            ("window", "창으로 보기"), ("back", "그리기로 돌아가기 (Esc)")]:
            b = QPushButton(label, self)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            lay.addWidget(b)
            self.buttons[name] = b
        self.adjustSize()

    def trigger(self, name: str) -> None:
        self.action.emit(name)


class OverlayWindow(QWidget):
    def __init__(self, controller, monitor, image, windows=()):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.c = controller
        self.monitor = monitor
        self.image = image
        self.windows = list(windows)
        self.scale = monitor.scale or 1.0
        self.pixmap = bgr_to_pixmap(image, self.scale)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        s = controller.settings
        self.toolbar = Toolbar(self, tool=s.last_tool, color=s.last_color, width=s.last_width, recent=s.recent_colors,
                               font_family=s.last_font_family, highlight_color=s.last_highlight_color,
                               text_bg=s.last_text_bg)
        self.toolbar.hide()
        self.toolbar.toolChanged.connect(self._tool_changed)
        self.toolbar.action.connect(controller.on_toolbar_action)
        self.toolbar.styleChanged.connect(self._style_changed)
        self.toolbar.symbolChosen.connect(self._symbol_chosen)
        self.side_bar = SideBar(self)
        self.side_bar.hide()
        self.side_bar.action.connect(controller.on_toolbar_action)
        self.ocr_bar = OcrBar(self)
        self.ocr_bar.hide()
        self.ocr_bar.action.connect(controller.on_ocr_action)
        self.tool = self.toolbar.tool
        self._press = None        # local QPointF where the mouse went down
        self._cursor = None       # local QPointF
        self._moved = False
        self._current: Shape | None = None
        self._move_index = None
        self._editor: QLineEdit | None = None
        self._pending_symbol: str | None = None   # picked with no text box open: goes in the next one
        self.hover_window = None
        self.selected: int | None = None     # index of the shape picked with the select tool
        self.ocr_lines = None                # recognized lines (selection coords) while in text mode
        self._ocr_sel = None                 # last dragged text rectangle (selection coords)

    def release(self) -> None:
        """Drop the frozen screenshot after a capture ends (a 4K frame is ~33 MB + its pixmap)."""
        self.image = np.zeros((8, 8, 3), np.uint8)
        self.pixmap = bgr_to_pixmap(self.image, self.scale)
        self.windows = []
        self._current = None
        self.selected = None
        self.ocr_lines = self._ocr_sel = None
        self.ocr_bar.hide()

    def reset(self, monitor, image, windows=()) -> None:
        """Reuse a pre-created window for a new capture (much faster than creating one)."""
        self.monitor = monitor
        self.image = image
        self.windows = list(windows)
        self.scale = monitor.scale or 1.0
        self.pixmap = bgr_to_pixmap(image, self.scale)
        self._press = self._cursor = self._current = self._move_index = None
        self._moved = False
        self.hover_window = None
        if self._editor is not None:
            self._editor.hide()
            self._editor.deleteLater()
            self._editor = None
        self.toolbar.hide()
        self.side_bar.hide()
        self.ocr_bar.hide()
        self.selected = None
        self._pending_symbol = None
        self.ocr_lines = self._ocr_sel = None
        self.update()

    # --- selected shape & style -------------------------------------------------
    _STYLE_ATTR = {"color": "color", "width": "line_width", "fill": "fill", "opacity": "opacity",
                   "font_size": "font_size", "bold": "bold", "italic": "italic",
                   "underline": "underline", "strike": "strike", "font_family": "font_family", "bg": "bg"}
    _TEXT_ONLY = {"font_size", "bold", "italic", "underline", "strike", "font_family", "bg"}

    def _style_changed(self, name: str) -> None:
        if self._editor is not None:
            self._editor.apply_style()
        if name not in self._STYLE_ATTR:   # e.g. the highlighter's own ink: used for new marks only
            return
        doc = self.c.session.document
        if self.selected is None or doc is None or not 0 <= self.selected < len(doc.shapes):
            return
        shape = doc.shapes[self.selected]
        if name in self._TEXT_ONLY and shape.kind != "text":
            return
        value = getattr(self.toolbar, self._STYLE_ATTR[name])
        doc.update(self.selected, **{name: value})
        self.update()

    def _symbol_chosen(self, ch: str) -> None:
        """Symbol picker: into the open text box at its cursor, else onto the selected text,
        else into the next text box the user opens."""
        doc = self.c.session.document
        if self._editor is not None:
            self._editor.insert(ch)
            self._editor.setFocus()
            self._editor._fit()
        elif (self.selected is not None and doc is not None and 0 <= self.selected < len(doc.shapes)
              and doc.shapes[self.selected].kind == "text"):
            doc.update(self.selected, text=doc.shapes[self.selected].text + ch)
        else:
            self._pending_symbol = ch
            if self.tool != "text":
                self.set_tool("text")
            self.c.notify(f"'{ch}' 을(를) 넣을 곳을 클릭하세요.")
        self.update()

    def _select(self, index: int | None) -> None:
        self.selected = index
        doc = self.c.session.document
        is_text = index is not None and doc.shapes[index].kind == "text"
        if is_text:
            self.toolbar.load_text_style(doc.shapes[index])
        self.toolbar.show_text_style(is_text or self.tool == "text")
        self.update()

    # --- text mode (drag to copy part of the recognized text) ----------------------
    def enter_ocr_mode(self, lines) -> None:
        self.ocr_lines = list(lines)
        self._ocr_sel = None
        self.toolbar.hide()
        tb = self.toolbar
        self.ocr_bar.adjustSize()
        self.ocr_bar.move(tb.pos())
        self.ocr_bar.show()
        self.ocr_bar.raise_()
        self.setCursor(Qt.IBeamCursor)
        self.setFocus()
        self.update()

    def exit_ocr_mode(self) -> None:
        self.ocr_lines = self._ocr_sel = None
        self.ocr_bar.hide()
        self.setCursor(Qt.ArrowCursor if self.tool == "select" else Qt.CrossCursor)
        self.show_toolbar()
        self.update()

    # --- geometry helpers ------------------------------------------------------
    def place(self) -> None:
        """Cover exactly the Qt screen that shows this monitor. Qt screen names are marketing
        names ("SAMSUNG"), not GDI names ("\\\\.\\DISPLAY1"), so match by geometry."""
        screens = QGuiApplication.screens()
        cand = [(s.name(), s.geometry().getRect(), s.devicePixelRatio()) for s in screens]
        name = match_screen(self.monitor, cand)
        scr = next((s for s in screens if s.name() == name), None)
        r = self.monitor.rect
        if scr is not None:
            g, dpr = scr.geometry(), scr.devicePixelRatio()
            exact = (abs(g.x() - r.x) <= 2 and abs(g.y() - r.y) <= 2
                     and abs(g.width() * dpr - r.w) <= 2 and abs(g.height() * dpr - r.h) <= 2)
            self.setScreen(scr)
            if exact:
                if abs(dpr - self.scale) > 0.01:  # trust Qt's ratio for drawing the frozen frame
                    self.scale = dpr
                    self.pixmap = bgr_to_pixmap(self.image, dpr)
                self.setGeometry(g)
                return
        self.setGeometry(QRect(round(r.x / self.scale), round(r.y / self.scale),
                               round(r.w / self.scale), round(r.h / self.scale)))

    def to_phys(self, p: QPointF) -> tuple[int, int]:
        return (round(self.monitor.rect.x + p.x() * self.scale), round(self.monitor.rect.y + p.y() * self.scale))

    def to_local(self, x: float, y: float) -> QPointF:
        return QPointF((x - self.monitor.rect.x) / self.scale, (y - self.monitor.rect.y) / self.scale)

    def local_rect(self, r: Rect) -> QRectF:
        tl = self.to_local(r.x, r.y)
        return QRectF(tl.x(), tl.y(), r.w / self.scale, r.h / self.scale)

    def to_doc(self, p: QPointF) -> tuple[float, float]:
        sel = self.c.session.selection
        x, y = self.to_phys(p)
        return (x - sel.x, y - sel.y)

    def crop(self, sel: Rect):
        x, y = sel.x - self.monitor.rect.x, sel.y - self.monitor.rect.y
        return np.ascontiguousarray(self.image[y:y + sel.h, x:x + sel.w, :3])  # BGR copy of the region only

    @property
    def active(self) -> bool:
        return self.c.active_overlay is self

    def _selection_here(self) -> Rect | None:
        return self.c.session.selection if self.active else None

    # --- toolbar ---------------------------------------------------------------
    def set_tool(self, name: str) -> None:
        self.toolbar.set_tool(name)

    def set_color(self, color: str) -> None:
        self.toolbar.set_color(color)

    def _tool_changed(self, name: str) -> None:
        self.close_text_editor()
        self.tool = name
        self.setCursor(Qt.ArrowCursor if name == "select" else Qt.CrossCursor)

    def show_toolbar(self) -> None:
        sel = self._selection_here()
        if sel is None:
            self.toolbar.hide()
            self.side_bar.hide()
            return
        if self.ocr_lines is not None:  # text mode: the text bar takes the toolbar's place
            self.enter_ocr_mode(self.ocr_lines)
        tb = self.toolbar
        tb.arrange(self.width() - 16)
        lr = self.local_rect(sel)
        local = Rect(int(lr.x()), int(lr.y()), int(lr.width()), int(lr.height()))
        screen = Rect(0, 0, self.width(), self.height())
        sb = self.side_bar
        sb.fit_height(int(self.height() * 0.6))
        (x, y), (sx, sy) = layout_bars(local, screen, (tb.width(), tb.height()), (sb.width(), sb.height()))
        tb.move(x, y)
        if self.ocr_lines is None:
            tb.show()
            tb.raise_()
        else:
            self.ocr_bar.move(x, y)
        sb.move(sx, sy)
        sb.show()
        sb.raise_()

    # --- mouse -----------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        self._press, self._cursor, self._moved = pos, pos, False
        st = self.c.session.state
        if st is State.EDITING and self.active:
            self._begin_edit(pos)
        self.update()

    def _inside_selection(self, pos) -> bool:
        return self.local_rect(self.c.session.selection).contains(pos)

    def _begin_edit(self, pos):
        doc = self.c.session.document
        if self._editor is not None:
            # a click anywhere else finishes the open text box (empty -> it just disappears);
            # this click does not start anything new
            self.close_text_editor()
            self._press = None
            return
        if not self._inside_selection(pos):
            self._press = None
            return
        d = self.to_doc(pos)
        tb = self.toolbar
        if self.ocr_lines is not None:   # text mode: this drag selects text
            return
        if self.tool == "step":
            doc.add_step(d, tb.color)
            self._press = None
        elif self.tool == "text":
            self._open_text_editor(pos)
            self._press = None
        elif self.tool == "select":
            self._move_index = None
            for i in range(len(doc.shapes) - 1, -1, -1):
                if doc.shapes[i].kind == "clip":   # the crop outline is not an object to pick
                    continue
                x1, y1, x2, y2 = doc.shapes[i].bbox()
                if x1 - 6 <= d[0] <= x2 + 6 and y1 - 6 <= d[1] <= y2 + 6:
                    self._move_index = i
                    break
            self._select(self._move_index)
        elif self.tool == "lasso":
            self._current = Shape(kind="clip", points=[d])
        else:
            color = tb.highlight_color if self.tool == "highlight" else tb.color
            self._current = Shape(kind=self.tool, points=[d, d], color=color, width=tb.line_width,
                                  fill=tb.fill, opacity=tb.opacity)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._cursor = pos
        st = self.c.session.state
        if self._press is not None and (pos - self._press).manhattanLength() > 3:
            self._moved = True
        if st is State.SELECTING:
            if self._press is None:
                from ..platform.windows import window_at
                self.hover_window = window_at(self.to_phys(pos), self.windows)
        elif st is State.EDITING and self._current is not None:
            d = self.to_doc(pos)
            sel = self.c.session.selection
            d = (min(max(d[0], 0), sel.w), min(max(d[1], 0), sel.h))
            if self._current.kind in ("pen", "curve", "clip"):
                self._current.points.append(d)
            else:
                self._current.points[1] = d
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        pos = e.position()
        st = self.c.session.state
        press, self._press = self._press, None
        if st is State.SELECTING:
            if self._moved or (pos - press).manhattanLength() > 3:
                self.c.on_drag(self.to_phys(press), self.to_phys(pos), self)
            elif self.hover_window is not None:
                self.c.on_select_rect(self.hover_window.rect, self, window=self.hover_window)
        elif st is State.EDITING:
            doc = self.c.session.document
            if self.ocr_lines is not None:
                a, b = self.to_doc(press), self.to_doc(pos)
                rect = (min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]), abs(b[1] - a[1]))
                if rect[2] > 2 and rect[3] > 2:
                    self._ocr_sel = rect
                    self.c.copy_ocr_selection(rect)
            elif self._current is not None:
                self._current.points[-1] = self.to_doc(pos) if self._current.kind not in ("pen", "curve", "clip") \
                    else self._current.points[-1]
                sel = self.c.session.selection
                self._current.points = [(min(max(x, 0), sel.w), min(max(y, 0), sel.h)) for x, y in self._current.points]
                if self._current.kind == "clip" and polygon(self._current.points, sel.w, sel.h) is None:
                    self.c.notify("자를 모양이 너무 작습니다. 남길 부분을 크게 따라 그려 주세요.")
                else:
                    doc.add(self._current)
                self._current = None
            elif self._move_index is not None:
                a, b = self.to_doc(press), self.to_doc(pos)
                if self._moved:
                    doc.move(self._move_index, b[0] - a[0], b[1] - a[1])
                self._move_index = None
        self.update()

    # --- text tool ---------------------------------------------------------------
    def _open_text_editor(self, pos):
        self.close_text_editor()   # there is never more than one text box
        ed = TextEditor(self, self.toolbar, self.scale)
        ed.move(int(pos.x()), int(pos.y()))
        ed.doc_point = self.to_doc(pos)
        if self._pending_symbol:
            ed.setText(self._pending_symbol)
            ed._fit()
            self._pending_symbol = None
        ed.show()
        ed.setFocus()
        ed.returnPressed.connect(lambda: self.close_text_editor(ed))
        ed.editingFinished.connect(lambda: self._editor_left(ed))
        self._editor = ed

    def _editor_left(self, ed) -> None:
        """Focus left the text box. A toolbar popup (symbols, background, palette) takes focus
        while it is open; the box must stay open for the symbol or color to go into it."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activePopupWidget() is not None:
            return
        self.close_text_editor(ed)

    def close_text_editor(self, ed=None) -> None:
        """Finish the open text box: add its text if something was typed, then remove it.
        `ed` (from the box's own signals) is ignored unless it is still the open box."""
        cur = self._editor
        if cur is None or (ed is not None and ed is not cur):
            return
        self._editor = None
        text = cur.text()
        doc = self.c.session.document
        if text.strip() and doc is not None:
            tb = self.toolbar
            doc.add(Shape(kind="text", points=[cur.doc_point], text=text, color=tb.color, width=tb.line_width,
                          font_size=tb.font_size, bold=tb.bold, italic=tb.italic, underline=tb.underline,
                          strike=tb.strike, font_family=tb.font_family, bg=tb.bg))
        cur.hide()
        cur.deleteLater()
        self.setFocus()
        self.update()

    # --- keyboard ------------------------------------------------------------------
    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        ctrl, shift = bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier)
        st = self.c.session.state
        if k == Qt.Key_Escape:
            if self.ocr_lines is not None:
                self.exit_ocr_mode()      # leave text mode, keep the capture
            else:
                self.c.cancel()
            return
        if st is State.SELECTING:
            if k == Qt.Key_C:
                self.c.copy_color(self, QPointF(self.mapFromGlobal(QCursor.pos())))
            return
        if st is not State.EDITING or not self.active:
            return
        doc = self.c.session.document
        tb = self.toolbar
        if self.ocr_lines is not None and (k in (Qt.Key_Return, Qt.Key_Enter) or (ctrl and k == Qt.Key_C)):
            self.c.on_ocr_action("all")
        elif k in (Qt.Key_Return, Qt.Key_Enter) or (ctrl and k == Qt.Key_C):
            self.c.finish("copy")
        elif ctrl and k in TEXT_STYLE_KEYS:
            tb.toggle_style(TEXT_STYLE_KEYS[k])
        elif ctrl and k in (Qt.Key_BracketRight, Qt.Key_BracketLeft):
            tb.bump_font(1 if k == Qt.Key_BracketRight else -1)
        elif not ctrl and k in (Qt.Key_BracketRight, Qt.Key_BracketLeft):
            step = 5 if shift else 1
            tb.bump_width(step if k == Qt.Key_BracketRight else -step)
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected is not None:
            doc.delete(self.selected)
            self._select(None)
        elif ctrl and k == Qt.Key_S:
            self.c.finish("save_as" if shift else "save")
        elif k == Qt.Key_F3:
            self.c.finish("pin")
        elif ctrl and (k == Qt.Key_Y or (shift and k == Qt.Key_Z)):
            doc.redo()
        elif ctrl and k == Qt.Key_Z:
            doc.undo()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if shift else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            self.c.nudge(dx, dy)
        elif k in TOOL_KEYS and not ctrl:
            self.set_tool(TOOL_KEYS[k])
        self.update()

    # --- painting -----------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pixmap)
        st = self.c.session.state
        sel = self._selection_here()
        preview = None
        if st is State.SELECTING and self._press is not None and self._cursor is not None and self._moved:
            preview = QRectF(self._press, self._cursor).normalized()
        hole = self.local_rect(sel) if sel else preview
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if hole is not None:
            inner = QPainterPath()
            inner.addRect(hole)
            path = path.subtracted(inner)
        p.fillPath(path, DIM)
        if st is State.SELECTING and hole is None and self.hover_window is not None:
            wr = self.local_rect(self.hover_window.rect).intersected(QRectF(self.rect()))
            p.setPen(QPen(ACCENT, 2, Qt.DashLine))
            p.fillRect(wr, QColor(76, 141, 255, 30))
            p.drawRect(wr)
            self._label(p, wr.topLeft(), self.hover_label())
        if hole is not None:
            p.setPen(QPen(ACCENT, 2))
            p.drawRect(hole)
            w = sel.w if sel else round(hole.width() * self.scale)
            h = sel.h if sel else round(hole.height() * self.scale)
            self._label(p, hole.topLeft(), f"{w} × {h}")
        if sel is not None:
            self._paint_annotations(p, sel)
        if st is State.SELECTING and self._cursor is not None and not self._moved:
            self._paint_magnifier(p)
        self._paint_hint(p, st)
        p.end()

    def _paint_annotations(self, p: QPainter, sel: Rect):
        doc = self.c.session.document
        shapes = list(doc.shapes) + ([self._current] if self._current else [])
        lr = self.local_rect(sel)
        if any(s.kind == "mosaic" for s in shapes):
            mosaic = apply_mosaic(self.crop(sel), shapes)
            p.drawImage(lr, bgr_to_qimage(mosaic))
        p.save()
        p.setClipRect(lr)
        p.translate(lr.topLeft())
        p.scale(1 / self.scale, 1 / self.scale)
        paint_document(p, shapes)
        self._paint_clip(p, sel, doc.clip, self._current)
        if self.selected is not None and 0 <= self.selected < len(doc.shapes):
            x1, y1, x2, y2 = doc.shapes[self.selected].bbox()
            pen = QPen(ACCENT, 1.5 * self.scale, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x1 - 5, y1 - 5, x2 - x1 + 10, y2 - y1 + 10))
        if self.ocr_lines is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(76, 141, 255, 40))
            for l in self.ocr_lines:
                p.drawRect(QRectF(*l.box))
            if self._ocr_sel is not None:
                p.setBrush(QColor(76, 141, 255, 70))
                p.setPen(QPen(ACCENT, 1.5 * self.scale))
                p.drawRect(QRectF(*self._ocr_sel))
            if self._press is not None and self._cursor is not None and self._moved:
                a, b = self.to_doc(self._press), self.to_doc(self._cursor)
                p.setBrush(QColor(76, 141, 255, 50))
                p.setPen(QPen(ACCENT, 1.5 * self.scale, Qt.DashLine))
                p.drawRect(QRectF(min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]), abs(b[1] - a[1])))
        p.restore()

    def _paint_clip(self, p: QPainter, sel: Rect, clip, current) -> None:
        """Freeform crop: darken what will be cut away; dashed outline while drawing."""
        if clip is not None:
            outline = QPainterPath()
            outline.addPolygon(QPolygonF([QPointF(x, y) for x, y in clip]))
            outline.closeSubpath()
            outside = QPainterPath()
            outside.addRect(QRectF(0, 0, sel.w, sel.h))
            p.fillPath(outside.subtracted(outline), QColor(15, 18, 24, 150))
            p.setPen(QPen(ACCENT, 2 * self.scale, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPath(outline)
        if current is not None and current.kind == "clip" and len(current.points) > 1:
            p.setPen(QPen(ACCENT, 2 * self.scale, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in current.points]))

    def _label(self, p: QPainter, at: QPointF, text: str):
        f = QFont(FONT_FAMILY)
        f.setPixelSize(12)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 16
        y = at.y() - 26 if at.y() > 30 else at.y() + 6
        r = QRectF(at.x(), y, w, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 18, 24, 220))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, Qt.AlignCenter, text)

    def _paint_magnifier(self, p: QPainter):
        cx, cy = self.to_phys(self._cursor)
        lx, ly = cx - self.monitor.rect.x, cy - self.monitor.rect.y
        n, z = 11, 12
        size = n * z
        ox = self._cursor.x() + 20
        oy = self._cursor.y() + 20
        if ox + size > self.width():
            ox = self._cursor.x() - 20 - size
        if oy + size + 44 > self.height():
            oy = self._cursor.y() - 20 - size - 44
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(27, 31, 38))
        p.drawRoundedRect(QRectF(ox - 4, oy - 4, size + 8, size + 52), 8, 8)
        h, w = self.image.shape[:2]
        for j in range(n):
            for i in range(n):
                x, y = lx + i - n // 2, ly + j - n // 2
                if 0 <= x < w and 0 <= y < h:
                    b, g, r = (int(v) for v in self.image[y, x][:3])
                    p.fillRect(QRectF(ox + i * z, oy + j * z, z, z), QColor(r, g, b))
        p.setPen(QPen(QColor("#FF3B3B"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(ox + (n // 2) * z, oy + (n // 2) * z, z, z))
        hexc = pixel_color(self.image, lx, ly) or "-"
        f = QFont(FONT_FAMILY)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(ox, oy + size + 4, size, 18), Qt.AlignLeft, f"{cx}, {cy}   {hexc}")
        p.setPen(QColor("#AEB4BD"))
        p.drawText(QRectF(ox, oy + size + 22, size, 18), Qt.AlignLeft, "C: 색상 복사")
        p.restore()

    def hover_label(self) -> str:
        w = self.hover_window
        if w is None:
            return ""
        name = (w.title or "창")[:40]
        r, m = w.rect, self.monitor.rect
        inside = r.x >= m.x and r.y >= m.y and r.right <= m.right and r.bottom <= m.bottom
        if inside:
            return f"{name} · 클릭하면 창 전체 선택"
        return f"{name} · 클릭하면 창 전체 (다른 모니터·화면 밖에 걸친 부분까지 한 장으로)"

    def tip_text(self) -> str:
        if not getattr(self.c, "tip_active", False) or self.c.session.state is not State.SELECTING:
            return ""
        return ("팁: 창의 제목줄(또는 창 위 아무 곳)을 클릭하면 그 창 전체가 캡처됩니다. "
                "두 모니터에 걸친 창도 한 장으로 찍힙니다.")

    def _paint_hint(self, p: QPainter, st):
        tip = self.tip_text()
        if tip and self.active is False and self.c.session.state is State.SELECTING:
            f = QFont(FONT_FAMILY)
            f.setPixelSize(15)
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(tip) + 40
            r = QRectF((self.width() - w) / 2, 60, w, 40)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(31, 95, 209, 235))
            p.drawRoundedRect(r, 10, 10)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(r, Qt.AlignCenter, tip)
        if st is State.SELECTING:
            text = "드래그로 영역 선택 · 창(제목줄)을 클릭하면 그 창 전체 · C 색상 복사 · Esc 취소"
        elif self.active and self.ocr_lines is not None:
            text = "글자 위를 드래그하면 그 부분만 복사 · Enter 전체 복사 · Esc 그리기로 돌아가기"
        elif self.active and self.tool == "lasso":
            text = "남길 부분의 테두리를 따라 그리세요 · 다시 그리면 새 모양 · Ctrl+Z 되돌리기 · Enter 복사"
        elif self.active:
            text = ("Enter 복사 · Ctrl+S 저장 · F3 고정 · [ ] 두께 · 선택 후 Delete 삭제 · "
                    "Ctrl+Z 되돌리기 · Esc 취소")
        else:
            return
        f = QFont(FONT_FAMILY)
        f.setPixelSize(13)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 32
        r = QRectF((self.width() - w) / 2, 16, w, 34)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 18, 24, 215))
        p.drawRoundedRect(r, 8, 8)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, Qt.AlignCenter, text)
