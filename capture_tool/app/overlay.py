"""Full-screen frozen overlay for one monitor: select a region, then draw on it in place.

Coordinates: widget-local logical px <-> global physical px (monitor origin + local * scale).
Annotations (core Document) use physical px relative to the selection."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLineEdit, QWidget

from ..core.annotations import Shape
from ..core.color import pixel_color
from ..core.geometry import Rect, layout_bars
from ..core.session import State
from .render import FONT_FAMILY, apply_mosaic, bgr_to_pixmap, bgr_to_qimage, paint_document
from .side_bar import SideBar
from .toolbar import Toolbar

DIM = QColor(15, 18, 24, 140)
ACCENT = QColor("#4C8DFF")
TOOL_KEYS = {Qt.Key_V: "select", Qt.Key_R: "rect", Qt.Key_O: "ellipse", Qt.Key_L: "line", Qt.Key_A: "arrow",
             Qt.Key_C: "curve", Qt.Key_P: "pen", Qt.Key_T: "text", Qt.Key_N: "step", Qt.Key_H: "highlight",
             Qt.Key_M: "mosaic"}
BOX_TOOLS = {"rect", "ellipse", "highlight", "mosaic", "line", "arrow"}


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
        self.toolbar = Toolbar(self, tool=s.last_tool, color=s.last_color, width=s.last_width, recent=s.recent_colors)
        self.toolbar.hide()
        self.toolbar.toolChanged.connect(self._tool_changed)
        self.toolbar.action.connect(controller.on_toolbar_action)
        self.side_bar = SideBar(self)
        self.side_bar.hide()
        self.side_bar.action.connect(controller.on_toolbar_action)
        self.tool = self.toolbar.tool
        self._press = None        # local QPointF where the mouse went down
        self._cursor = None       # local QPointF
        self._moved = False
        self._current: Shape | None = None
        self._move_index = None
        self._editor: QLineEdit | None = None
        self.hover_window = None

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
            self._editor.deleteLater()
            self._editor = None
        self.toolbar.hide()
        self.side_bar.hide()
        self.update()

    # --- geometry helpers ------------------------------------------------------
    def place(self) -> None:
        for scr in QGuiApplication.screens():
            if scr.name() == self.monitor.name:
                self.setScreen(scr)
                self.setGeometry(scr.geometry())
                return
        r = self.monitor.rect
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
        self.tool = name
        self.setCursor(Qt.ArrowCursor if name == "select" else Qt.CrossCursor)

    def show_toolbar(self) -> None:
        sel = self._selection_here()
        if sel is None:
            self.toolbar.hide()
            self.side_bar.hide()
            return
        tb = self.toolbar
        tb.arrange(self.width() - 16)
        lr = self.local_rect(sel)
        local = Rect(int(lr.x()), int(lr.y()), int(lr.width()), int(lr.height()))
        screen = Rect(0, 0, self.width(), self.height())
        sb = self.side_bar
        (x, y), (sx, sy) = layout_bars(local, screen, (tb.width(), tb.height()), (sb.width(), sb.height()))
        tb.move(x, y)
        tb.show()
        tb.raise_()
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
        if not self._inside_selection(pos):
            self._press = None
            return
        d = self.to_doc(pos)
        tb = self.toolbar
        if self.tool == "step":
            doc.add_step(d, tb.color)
            self._press = None
        elif self.tool == "text":
            self._open_text_editor(pos)
            self._press = None
        elif self.tool == "select":
            self._move_index = None
            for i in range(len(doc.shapes) - 1, -1, -1):
                x1, y1, x2, y2 = doc.shapes[i].bbox()
                if x1 - 6 <= d[0] <= x2 + 6 and y1 - 6 <= d[1] <= y2 + 6:
                    self._move_index = i
                    break
        else:
            self._current = Shape(kind=self.tool, points=[d, d], color=tb.color, width=tb.line_width,
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
            if self._current.kind in ("pen", "curve"):
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
                self.c.on_select_rect(self.hover_window.rect, self)
        elif st is State.EDITING:
            doc = self.c.session.document
            if self._current is not None:
                self._current.points[-1] = self.to_doc(pos) if self._current.kind not in ("pen", "curve") \
                    else self._current.points[-1]
                sel = self.c.session.selection
                self._current.points = [(min(max(x, 0), sel.w), min(max(y, 0), sel.h)) for x, y in self._current.points]
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
        ed = QLineEdit(self)
        ed.setPlaceholderText("텍스트 입력 후 Enter")
        ed.setStyleSheet(f"QLineEdit {{ background: rgba(255,255,255,230); color: {self.toolbar.color};"
                         " border: 1px dashed #4C8DFF; font-weight: bold; }")
        ed.move(int(pos.x()), int(pos.y()))
        ed.resize(220, 30)
        ed.show()
        ed.setFocus()
        doc_point = self.to_doc(pos)

        def done():
            if self._editor is not ed:
                return
            self._editor = None
            if ed.text().strip():
                self.c.session.document.add(Shape(kind="text", points=[doc_point], text=ed.text(),
                                                  color=self.toolbar.color, width=self.toolbar.line_width))
            ed.deleteLater()
            self.setFocus()
            self.update()

        ed.returnPressed.connect(done)
        ed.editingFinished.connect(done)
        self._editor = ed

    # --- keyboard ------------------------------------------------------------------
    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        ctrl, shift = bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier)
        st = self.c.session.state
        if k == Qt.Key_Escape:
            self.c.cancel()
            return
        if st is State.SELECTING:
            if k == Qt.Key_C:
                self.c.copy_color(self, QPointF(self.mapFromGlobal(QCursor.pos())))
            return
        if st is not State.EDITING or not self.active:
            return
        doc = self.c.session.document
        if k in (Qt.Key_Return, Qt.Key_Enter) or (ctrl and k == Qt.Key_C):
            self.c.finish("copy")
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
            self._label(p, wr.topLeft(), f"{self.hover_window.title or '창'} · 클릭하면 선택")
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
        p.restore()

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

    def _paint_hint(self, p: QPainter, st):
        if st is State.SELECTING:
            text = "드래그로 영역 선택 · 클릭하면 창 선택 · C 색상 복사 · Esc 취소"
        elif self.active:
            text = "Enter 복사 · Ctrl+S 바로 저장 · Ctrl+Shift+S 위치 골라 저장 · F3 고정 · Ctrl+Z 되돌리기 · Esc 취소"
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
