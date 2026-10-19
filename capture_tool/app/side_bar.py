"""Quick-action icons floating next to the captured region: copy, save as, OCR, send to PowerPoint, pin.
Row mode: a favourites row the person arranges (core.bar_layout), the rest grouped under 전체."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QToolButton,
                               QVBoxLayout, QWidget)

from .. import edition
from ..core import bar_layout as bl
from . import icons

# (action, icon, label, tooltip, row): "basic" = the one-row bar, "extra" = shown under 전체 (the
# default arrangement; the person's own favourites decide the rows at run time)
ACTIONS = [
    ("copy", "copy", "복사", "클립보드에 복사하고 닫기 (Enter · Ctrl+C) — 영역을 고르면 이미 복사되어 있습니다", "basic"),
    ("autosave", "save", "자동저장", "켜 두면 캡처를 끝낼 때마다 저장 폴더에 파일로도 저장 (누를 때마다 켜기/끄기)", "basic"),
    ("text", "ocr", "텍스트", "이미지 속 글자를 인식해 복사", "basic"),
    ("translate", "translate", "번역", "캡처 속 글자를 바로 번역 — 텍스트를 먼저 누르지 않아도 됩니다 "
                                       "(텍스트 모드에서 드래그한 부분이 있으면 그 부분만)", "basic"),
    ("summarize", "summary", "요약", "캡처 속 글자를 바로 요약 — 텍스트를 먼저 누르지 않아도 됩니다", "basic"),
    ("table", "table", "표", "캡처 속 표를 칸 그대로 복사 — 엑셀·PowerPoint에 붙이면 고칠 수 있는 표", "basic"),
    ("ppt", "ppt", "PPT", "캡처한 그대로 PowerPoint에 넣기 — 그림(그린 것 포함), 텍스트 모드에서는 글자", "basic"),
    ("mail", "mail", "메일", "메일로 보내기 — 받는 사람을 고르면 네이버·Gmail 등의 쓰기 화면이 열리고, 도우미 창으로 붙여 넣기 "
                             "([보내기]는 직접)", "basic"),
    ("kakao", "talk", "카톡", "카카오톡으로 보내기 — 열려 있는 채팅방을 고르면 그곳에 붙여 넣습니다 "
                              "(카카오톡의 [전송]을 눌러야 보내집니다)", "basic"),
    ("search", "search", "검색", "검색 — 그림으로 찾기(구글·네이버, 검색창에 Ctrl+V) 또는 캡처 속 글자로 찾기(구글·네이버·파파고)",
     "basic"),
    ("pin", "pin", "고정", "캡처를 다른 모든 창 위에 계속 떠 있게 붙여 둡니다 — 여러 장 가능 (F3)", "basic"),
    ("more", "more", "전체", "모든 기능 펼치기 / 기본만 보기 (마지막 상태를 기억) — 버튼을 오른쪽 클릭하면 줄을 바꿀 수 있습니다", "basic"),
    ("save_as", "save_as", "다른 이름 저장", "저장 위치를 골라 저장 (Ctrl+Shift+S)", "extra"),
    ("resize", "resize", "크기 줄이기", "캡처를 작게 — 복사·저장·PDF가 줄인 크기로 (메일·업로드용)", "extra"),
    ("border", "border", "테두리", "캡처 둘레에 테두리(굵기·색)와 음영(그림자)을 넣어 복사·저장 — 미리 보기 제공", "extra"),
    ("transparent", "transparent", "배경 지우기", "종이·화면 바탕을 지우고 글씨·사인·도장만 남긴 투명 PNG로 복사·저장 — 색별로 남길 것 고르기, 미리 보기 (올가미로 따면 더 깔끔)", "extra"),
    ("rotate_left", "rotate_left", "왼쪽 회전", "반시계 방향으로 90° 돌려 편집 창에서 열기 — 돌린 그림으로 텍스트·표·PPT 모두 사용", "extra"),
    ("rotate_right", "rotate_right", "오른쪽 회전", "시계 방향으로 90° 돌려 편집 창에서 열기 (옆으로 찍은 사진·문서)", "extra"),
    ("pdf", "pdf", "PDF", "캡처를 PDF로 저장 — 긴 캡처는 여러 쪽으로", "extra"),
    ("print", "print", "인쇄", "캡처를 프린터로 인쇄 (용지에 맞춤)", "extra"),
    ("ppt_shapes", "shapes", "도형PPT", "도형을 알아봐서 PowerPoint에서 고칠 수 있는 도형으로 넣기", "extra"),
    ("scroll", "scroll", "스크롤", "아래로 자동 스크롤하며 길게 캡처 — 브라우저 창 전체를 고르면 페이지 처음부터 끝까지 (Esc 중지)",
     "extra"),
    ("link", "link", "링크", "링크 복사 — ① 파일 링크: 저장한 파일 위치(인터넷에 올리지 않음, 같은 PC·공유 폴더에서 열림) "
                             "② 인터넷 공유 링크: 누구나 열 수 있는 주소, 정해진 시간 뒤 자동 삭제", "extra"),
    ("open_folder", "folder", "저장 폴더", "저장 폴더 열기", "extra"),
    ("help", "help", "도움말", "처음 쓰는 분을 위한 따라하기 설명서 (F1)", "extra"),
]
LABELS = {name: label for name, _, label, _, _ in ACTIONS}

INK = "#E9ECF2"                  # icon and label colour on the dark bar

STYLE = """
QWidget#sidebar { background: #1B1F2A; border: 1px solid #353C4E; border-radius: 16px; }
QToolButton { border: none; border-radius: 10px; color: #E9ECF2; font-size: 11px; padding: 4px 0px; }
QToolButton:hover { background: #2D3446; color: #FFFFFF; }
QToolButton:pressed { background: #384158; }
QToolButton#primary { background: #3B7CF6; color: #FFFFFF; font-weight: 600; padding: 4px 6px; }
QToolButton#primary:hover { background: #5A92FA; }
QToolButton#tablebtn { padding-right: 22px; }
QToolButton#tablebtn::menu-button { border: none; width: 18px; border-top-right-radius: 10px;
                                    border-bottom-right-radius: 10px; }
QToolButton#tablebtn::menu-button:hover { background: #384158; }
QToolButton:checked { background: #20365E; color: #8FB6FF; }
QFrame#divider { background: #353C4E; }
QFrame#dropline { background: #5A92FA; border-radius: 1px; }
QFrame#dropzone { border: 2px solid #3B7CF6; border-radius: 10px; background: rgba(59, 124, 246, 40); }
QToolButton[landed="true"] { background: #20365E; border: 2px solid #5A92FA; }
QLabel#grouplabel { color: #8A93A6; font-size: 10px; padding: 0 2px 0 6px; }
QLabel#place { color: #FFD166; font-size: 10px; font-weight: 600; border: 1px solid #5A4C1E; border-radius: 6px;
               padding: 1px 5px; margin-left: 2px; }
QMenu { background: #1F2430; color: #E9ECF2; border: 1px solid #353C4E; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: #2F3B55; }
QMenu::item:disabled { color: #8A93A6; }
QMenu::indicator { width: 14px; height: 14px; left: 4px; }
QMenu::separator { height: 1px; background: #353C4E; margin: 5px 8px; }
"""


class SideBar(QWidget):
    """Quick actions for the capture. Row mode (default): the favourites row under the capture,
    the remaining buttons in groups on a second row when expanded (전체). Column mode: everything
    in a column in the same order (the edit window's right side). A button dragged along the
    favourites lands where the blue line is, a 전체 button dragged up joins them, a favourite
    dragged onto the 전체 rows leaves them; a right-click offers the same (bar:* actions, handled
    by the controller)."""
    action = Signal(str)
    DRAG_START = 6                    # px of movement before a press becomes a drag (a click is less)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(4, 6, 4, 6)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(4)
        self._extra = QWidget(self)               # the 전체 rows: their own spacing, not the first row's columns
        self._extra_rows = QVBoxLayout(self._extra)
        self._extra_rows.setContentsMargins(0, 0, 0, 0)
        self._extra_rows.setSpacing(4)
        self._max_width = 10_000                  # the 전체 buttons wrap to more rows past this
        self.columns = 0                  # 0 = row mode
        self.expanded = False
        self.buttons: dict[str, QToolButton] = {}
        self._dividers: list[QFrame] = []
        self.group_labels: list[QLabel] = []
        self.place_label = QLabel("", self)
        self.place_label.setObjectName("place")
        self.place_label.hide()
        self.column_order: list[str] = []
        self._press: tuple[str, QPoint] | None = None   # (button, where) of a left press that may become a drag
        self._drag: dict | None = None
        self.ghost: QLabel | None = None                 # the dragged button's picture under the pointer
        self._line = QFrame(self)                        # where the drop would land on the favourites
        self._line.setObjectName("dropline")
        self._line.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._line.hide()
        self._zone = QFrame(self)                        # the 전체 rows lit up as "drop here to leave the favourites"
        self._zone.setObjectName("dropzone")
        self._zone.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._zone.hide()
        for name, icon_name, label, tip, _row in ACTIONS:
            if not edition.has(name):
                continue                                   # the work edition has no KakaoTalk / mail at all
            b = QToolButton(self)
            primary = name == "copy"
            b.setObjectName("primary" if primary else "")
            b.setIcon(icons.icon(icon_name, "#FFFFFF" if primary else INK))
            b.setIconSize(QSize(20, 20))
            b.setText(label)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            if name == "autosave":
                b.setCheckable(True)
            if name == "link":
                b.clicked.connect(lambda _=False, btn=b: self._link_menu(btn))
            elif name == "kakao":
                b.clicked.connect(lambda _=False, btn=b: self._kakao_popup(btn))
            elif name == "table":
                from PySide6.QtWidgets import QMenu, QToolButton as _TB
                b.setPopupMode(_TB.MenuButtonPopup)
                b.setObjectName("tablebtn")          # room for the ▾ next to the label
                menu = QMenu(b)
                menu.aboutToShow.connect(lambda m=menu: self._fill_table_menu(m))
                b.setMenu(menu)
                b.clicked.connect(lambda _=False: self.action.emit("table"))
            elif name == "ppt_shapes":
                from PySide6.QtWidgets import QMenu, QToolButton as _TB
                b.setPopupMode(_TB.MenuButtonPopup)
                b.setObjectName("tablebtn")
                menu = QMenu(b)
                menu.aboutToShow.connect(lambda m=menu: self._fill_shapes_menu(m))
                b.setMenu(menu)
                b.clicked.connect(lambda _=False: self.action.emit("ppt_shapes"))
            elif name == "pin":
                b.clicked.connect(lambda _=False, btn=b: self.pin_menu().exec(btn.mapToGlobal(btn.rect().bottomLeft())))
            elif name == "search":
                if edition.has_web_search():
                    b.clicked.connect(lambda _=False, btn=b: self.search_menu().exec(btn.mapToGlobal(btn.rect().bottomLeft())))
                else:                                      # work: only the saved captures are searched
                    b.clicked.connect(lambda _=False: self.action.emit("search_local"))
            else:
                b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            b.installEventFilter(self)                     # dragging (below)
            self.buttons[name] = b
        self.layout_first, self.layout_groups = bl.rows(bl.default_profile("home"), available=list(self.buttons))
        self.place = ""
        self._arrange()

    # --- arrangement --------------------------------------------------------------------------
    def apply_layout(self, first: list[str], groups: list[tuple[str, list[str]]], place: str = "",
                     max_width: int | None = None) -> None:
        """The rows to show (core.bar_layout.rows), the place badge ("회사" or none) and how wide
        the bar may get (the 전체 buttons wrap past it - a small laptop screen)."""
        if max_width is not None and max_width != self._max_width:
            self._max_width = max_width
            self.layout_first = []                    # forces a new arrangement below
        first = [n for n in first if n in self.buttons]
        groups = [(label, [n for n in names if n in self.buttons]) for label, names in groups]
        groups = [(label, names) for label, names in groups if names]
        if (first, groups, place) == (self.layout_first, self.layout_groups, self.place):
            return
        self.layout_first, self.layout_groups, self.place = first, groups, place
        self._arrange()

    def _clear(self) -> None:
        for b in self.buttons.values():
            self._grid.removeWidget(b)
        self._grid.removeWidget(self._extra)
        self._grid.removeWidget(self.place_label)
        while self._extra_rows.count():               # the 전체 rows and everything in them
            item = self._extra_rows.takeAt(0)
            row = item.layout()
            if row is not None:
                while row.count():
                    row.takeAt(0)
                row.deleteLater()
        for w in self._dividers + self.group_labels:
            self._grid.removeWidget(w)
            w.hide()                                  # gone now, not when Qt deletes it later
            w.deleteLater()
        self._dividers, self.group_labels = [], []

    @staticmethod
    def _row_button(b) -> None:
        """A row-mode button: label beside the icon, never narrower than its text. (The grid gave
        the 전체 row only the first row's width when it was the wider one, and Qt then elided the
        long labels - 배경 지우기 became 배경 지… - BUG-117.)"""
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setMinimumSize(QSize(0, 40))
        b.setMaximumSize(QSize(16777215, 40))
        b.setMinimumWidth(b.sizeHint().width())

    def _divider(self, parent) -> QFrame:
        d = QFrame(parent)
        d.setObjectName("divider")
        d.setFixedSize(1, 22)
        d.show()
        self._dividers.append(d)
        return d

    def _arrange(self) -> None:
        self.cancel_drag()
        self._clear()
        placed = set(self.layout_first) | {n for _, names in self.layout_groups for n in names}
        for n, b in self.buttons.items():
            if n not in placed:
                b.setVisible(False)                   # hidden at this place
        if self.columns:
            self._extra.hide()                        # column: everything but the row-only switches
            self.place_label.hide()
            names = [n for n in self.layout_first if n not in ("more", "autosave")]
            names += [n for _, group in self.layout_groups for n in group if n not in ("more", "autosave")]
            self.column_order = names
            for n in names:
                self.buttons[n].setMinimumSize(QSize(0, 0))
                self.buttons[n].setMaximumSize(QSize(16777215, 16777215))
                self.buttons[n].setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            width = max([64] + [self.buttons[n].sizeHint().width() for n in names])   # the longest label fits
            for i, n in enumerate(names):
                b = self.buttons[n]
                b.setFixedSize(QSize(width, 54))
                self._grid.addWidget(b, i // self.columns, i % self.columns)
                b.setVisible(True)
            for n in ("more", "autosave"):
                if n in self.buttons:
                    self.buttons[n].setVisible(False)
        else:
            self.column_order = []
            col, group = 0, None
            for n in self.layout_first:
                g = bl.group_key(n)
                if group is not None and g != group:          # a thin line between groups
                    self._grid.addWidget(self._divider(self), 0, col, Qt.AlignVCenter)
                    col += 1
                group = g
                b = self.buttons[n]
                self._row_button(b)
                b.setVisible(True)
                self._grid.addWidget(b, 0, col)
                col += 1
            if self.place:
                self.place_label.setText(self.place)
                self._grid.addWidget(self.place_label, 0, col, Qt.AlignVCenter)
                self.place_label.show()
                col += 1
            else:
                self.place_label.hide()
            row, used = None, 0

            def put(w, width):                       # into the current 전체 row, or a new one past max_width
                nonlocal row, used
                if row is None or (used and used + width + 4 > self._max_width):
                    if row is not None:
                        row.addStretch(1)
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(4)
                    self._extra_rows.addLayout(row)
                    used = 0
                row.addWidget(w)
                used += width + 4
            for gi, (label, names) in enumerate(self.layout_groups):
                if gi and used:
                    put(self._divider(self._extra), 1)
                lb = QLabel(label, self._extra)
                lb.setObjectName("grouplabel")
                lb.show()
                self.group_labels.append(lb)
                put(lb, lb.sizeHint().width())
                for n in names:
                    b = self.buttons[n]
                    self._row_button(b)
                    put(b, b.sizeHint().width())
                    b.setVisible(self.expanded)
            if row is not None:
                row.addStretch(1)
            self._grid.addWidget(self._extra, 1, 0, 1, max(1, col))
            self._extra.setVisible(self.expanded and bool(self.layout_groups))
            if "more" in self.buttons:
                self.buttons["more"].setText("기본" if self.expanded else "전체")
        self._grid.invalidate()
        self.adjustSize()

    def set_columns(self, n: int) -> None:
        """Column mode with n columns (the edit window); 0 = back to the row."""
        self.columns = n
        self._arrange()

    def set_expanded(self, on: bool) -> None:
        self.expanded = bool(on)
        if not self.columns:
            self._arrange()

    def set_autosave(self, on: bool) -> None:
        b = self.buttons.get("autosave")
        if b is not None:
            b.setChecked(bool(on))
            b.setText("자동저장 켜짐" if on else "자동저장")
            if not self.columns:
                b.setMinimumWidth(0)
                self._row_button(b)                       # the new text's width, not the old one's
            self.adjustSize()

    def remove_action(self, name: str) -> None:
        b = self.buttons.pop(name, None)
        if b is not None:
            self._grid.removeWidget(b)
            b.hide()                       # gone right away, not only when Qt deletes it later
            b.setParent(None)
            b.deleteLater()
            self.layout_first = [n for n in self.layout_first if n != name]
            self.layout_groups = [(l, [n for n in ns if n != name]) for l, ns in self.layout_groups]
            self.layout_groups = [(l, ns) for l, ns in self.layout_groups if ns]
            self._arrange()

    def fit_height(self, max_height: int) -> None:
        """Column mode only: two columns when one would be too tall for the screen."""
        if not self.columns:
            return
        one = len(self.column_order) * 58 + 12
        want = 1 if one <= max_height else 2
        if want != self.columns:
            self.set_columns(want)

    def trigger(self, name: str) -> None:
        self.action.emit(name)

    # --- rearranging by right-click --------------------------------------------------------------
    def _button_at(self, pos) -> str | None:
        w = self.childAt(pos)
        while w is not None and w is not self:
            for n, b in self.buttons.items():
                if w is b:
                    return n
            w = w.parentWidget()
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            name = self._button_at(e.position().toPoint())
            if name is not None:
                self._show_bar_menu(name, e.globalPosition().toPoint())
                e.accept()
                return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        e.accept()                                     # the right-click press already opened the menu

    def _show_bar_menu(self, name: str, global_pos) -> None:
        self.bar_menu(name).exec(global_pos)

    def bar_menu(self, name: str):
        """What a button can do about its place: join or leave the favourites, move along the
        row, hide at this place; and the default arrangement back."""
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        label = LABELS.get(name, name)
        head = m.addAction(f"'{label}' 버튼")
        head.setEnabled(False)

        def item(text: str, key: str, enabled: bool = True):
            a = m.addAction(text)
            a.setData(key)
            a.setEnabled(enabled)
            a.triggered.connect(lambda _=False, k=key: self.action.emit(k))
            return a
        fixed = name in (bl.FIXED_FIRST, bl.FIXED_LAST)
        if not fixed:
            if name in self.layout_first:
                i = self.layout_first.index(name)
                item("즐겨찾기에서 빼기 — 전체 줄로", f"bar:fav_remove:{name}")
                item("왼쪽으로", f"bar:left:{name}", i > 1)
                item("오른쪽으로", f"bar:right:{name}", i < len(self.layout_first) - 2)
            else:
                item("즐겨찾기에 넣기 — 첫 줄 끝에", f"bar:fav_add:{name}")
            item("이 장소에서 숨기기 — 설정 → 버튼 막대에서 되살림", f"bar:hide:{name}")
            m.addSeparator()
        item("기본 배치로 되돌리기", "bar:reset")
        return m

    # --- rearranging by dragging ------------------------------------------------------------------
    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            name = next((n for n, b in self.buttons.items() if b is obj), None)
            fixed = name in (bl.FIXED_FIRST, bl.FIXED_LAST)
            self._press = (name, e.globalPosition().toPoint()) if name is not None and not fixed else None
        elif t == QEvent.MouseMove and self._press is not None:
            if not (e.buttons() & Qt.LeftButton):
                self._press = None
            else:
                gpos = e.globalPosition().toPoint()
                if self._drag is None and (gpos - self._press[1]).manhattanLength() >= self.DRAG_START:
                    self._start_drag(self._press[0], obj, gpos)
                if self._drag is not None:
                    self._update_drag(gpos)
                    return True
        elif t == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton:
            self._press = None
            if self._drag is not None:
                self._finish_drag(e.globalPosition().toPoint())
                return True                               # no click out of a drop
        return super().eventFilter(obj, e)

    def dragging(self) -> bool:
        return self._drag is not None

    def _start_drag(self, name: str, btn, gpos: QPoint) -> None:
        btn.setDown(False)
        pm = QPixmap(btn.size())                     # the button on a dark rounded card (its own grab() has
        pm.fill(Qt.transparent)                      # the palette's light background behind the light text)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#5A92FA"), 1))
        painter.setBrush(QColor("#2D3446"))
        painter.drawRoundedRect(pm.rect().adjusted(0, 0, -1, -1), 10, 10)
        btn.render(painter, QPoint(0, 0), QRegion(), QWidget.DrawChildren)
        painter.end()
        ghost = QLabel(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                       | Qt.WindowTransparentForInput)
        ghost.setAttribute(Qt.WA_TranslucentBackground, True)
        ghost.setAttribute(Qt.WA_ShowWithoutActivating, True)
        ghost.setPixmap(pm)
        ghost.resize(pm.size())
        ghost.setWindowOpacity(0.85)
        self.ghost = ghost
        dim = QGraphicsOpacityEffect(btn)
        dim.setOpacity(0.3)
        btn.setGraphicsEffect(dim)
        btn.setCursor(Qt.ClosedHandCursor)
        self._drag = {"name": name, "btn": btn, "offset": gpos - btn.mapToGlobal(QPoint(0, 0)), "target": None}
        ghost.move(gpos - self._drag["offset"])
        ghost.show()

    def _slots(self) -> list[tuple[str, QRect]]:
        """The buttons in slot order with their rectangles in the bar's coordinates."""
        names = self.column_order if self.columns else self.layout_first
        out = []
        for n in names:
            b = self.buttons.get(n)
            if b is not None and b.isVisible():
                out.append((n, QRect(b.mapTo(self, QPoint(0, 0)), b.size())))
        return out

    def _drop_target(self, pos: QPoint):
        """What a drop at `pos` (bar coordinates) would do: ("after", anchor, line rect) for a
        place on the favourites, ("remove", zone rect) for the 전체 rows, None = cancel."""
        name = self._drag["name"]
        slots = self._slots()
        if not slots:
            return None
        if self.columns:
            if not self.rect().adjusted(-30, -30, 30, 30).contains(pos):
                return None
            row_y = min((r.center().y() for _, r in slots), key=lambda y: abs(y - pos.y()))
            k = 0
            for _, r in slots:
                c = r.center()
                if c.y() < row_y - 1 or (abs(c.y() - row_y) <= 1 and (c.y() < pos.y() if self.columns == 1 else c.x() < pos.x())):
                    k += 1
            k = max(1, k)
            fav_count = sum(1 for n, _ in slots if n in self.layout_first)
            if k <= fav_count:
                prev = slots[k - 1][1]
                return ("after", slots[k - 1][0], QRect(prev.left(), prev.bottom() + 1, prev.width(), 3))
            if name in self.layout_first:
                rest = [r for n, r in slots if n not in self.layout_first]
                zone = rest[0]
                for r in rest[1:]:
                    zone = zone.united(r)
                return ("remove", zone.adjusted(-3, -3, 3, 3))
            return None
        top = min(r.top() for _, r in slots)
        bottom = max(r.bottom() for _, r in slots)
        band = QRect(0, top - 16, self.width(), bottom - top + 32).adjusted(-30, 0, 30, 0)
        if band.contains(pos):
            k = sum(1 for _, r in slots if r.center().x() < pos.x())
            k = min(max(k, 1), len(slots) - 1)
            prev, nxt = slots[k - 1][1], slots[k][1]
            x = (prev.right() + nxt.left()) // 2 - 1
            return ("after", slots[k - 1][0], QRect(x, nxt.top(), 3, nxt.height()))
        if self._extra.isVisible() and name in self.layout_first:
            zone = QRect(self._extra.mapTo(self, QPoint(0, 0)), self._extra.size())
            if zone.adjusted(-8, -8, 8, 8).contains(pos):
                return ("remove", zone.adjusted(-3, -3, 3, 3))
        return None

    def _update_drag(self, gpos: QPoint) -> None:
        d = self._drag
        self.ghost.move(gpos - d["offset"])
        target = self._drop_target(self.mapFromGlobal(gpos))
        d["target"] = target
        self._line.setVisible(bool(target) and target[0] == "after")
        self._zone.setVisible(bool(target) and target[0] == "remove")
        if target and target[0] == "after":
            self._line.setGeometry(target[2])
            self._line.raise_()
        elif target:
            self._zone.setGeometry(target[1])
            self._zone.raise_()
        self.ghost.setWindowOpacity(0.85 if target else 0.45)

    def _end_drag(self) -> dict | None:
        d, self._drag = self._drag, None
        if d is None:
            return None
        self._line.hide()
        self._zone.hide()
        if self.ghost is not None:
            self.ghost.hide()
            self.ghost.deleteLater()
            self.ghost = None
        btn = d["btn"]
        btn.setGraphicsEffect(None)
        btn.unsetCursor()
        btn.setDown(False)
        return d

    def cancel_drag(self) -> bool:
        """Esc (or a new arrangement) while dragging: back where it was. True if there was one."""
        self._press = None
        return self._end_drag() is not None

    def _finish_drag(self, gpos: QPoint) -> None:
        target = self._drop_target(self.mapFromGlobal(gpos))
        d = self._end_drag()
        if d is None or not target:
            return
        name = d["name"]
        if target[0] == "after":
            if target[1] == name:
                return
            self.action.emit(f"bar:fav_after:{name}:{target[1]}")
        else:
            self.action.emit(f"bar:fav_remove:{name}")
        self._flash(name)

    def _flash(self, name: str) -> None:
        """A short blue frame on the button that just landed."""
        b = self.buttons.get(name)
        if b is None:
            return
        b.setProperty("landed", True)
        b.style().unpolish(b)
        b.style().polish(b)

        def off():
            if b in self.buttons.values():
                b.setProperty("landed", False)
                b.style().unpolish(b)
                b.style().polish(b)
        QTimer.singleShot(600, off)

    # --- menus of single buttons ------------------------------------------------------------------
    kakao_provider = staticmethod(lambda: None)    # -> KakaoSender (set by the overlay)

    def kakao_menu(self, sender):
        """Open chats first (paste straight into one), then "open KakaoTalk"."""
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        if sender is None or not sender.installed():
            a = m.addAction("카카오톡이 설치되어 있지 않습니다 (캡처는 복사됩니다)")
            a.triggered.connect(lambda: self.action.emit("kakao_main"))
            return m
        chats = sender.chats()
        for hwnd, title in chats[:15]:
            a = m.addAction(f"💬 {title} — 이 채팅방에 붙여 넣기")
            a.triggered.connect(lambda _=False, h=hwnd: self.action.emit(f"kakao_chat:{h}"))
        if chats:
            m.addSeparator()
        b = m.addAction("카카오톡 열기 — 채팅방을 직접 골라 Ctrl+V")
        b.triggered.connect(lambda: self.action.emit("kakao_main"))
        return m

    settings_provider = staticmethod(lambda: None)    # -> Settings (set by the overlay)

    def _fill_shapes_menu(self, m) -> None:
        m.clear()
        a = m.addAction("도형 + 글자 그대로 (기본)")
        a.triggered.connect(lambda: self.action.emit("ppt_shapes"))
        b = m.addAction("글자를 하나의 상자로 합쳐서")
        b.setToolTip("흩어진 글자를 한 개의 텍스트 상자로 합쳐 PowerPoint에 넣습니다 (배너·문단에 좋음)")
        b.triggered.connect(lambda: self.action.emit("ppt_merge"))

    def shapes_menu_actions(self) -> list:
        return ["ppt_shapes", "ppt_merge"]

    def _fill_table_menu(self, m, settings=None) -> None:
        from PySide6.QtGui import QActionGroup
        m.clear()
        s = settings or self.settings_provider()
        target = getattr(s, "table_target", "excel")
        style = getattr(s, "table_style", "keep")
        for options, current, key in (((("excel", "엑셀에 넣기"), ("ppt", "PPT에 넣기"), ("word", "워드에 넣기")), target, "target"),
                                      ((("keep", "캡처 모양 그대로"), ("plain", "흰 바탕 · 검은 글씨")), style, "style")):
            group = QActionGroup(m)
            for val, label in options:
                a = m.addAction(label)
                a.setCheckable(True)
                a.setChecked(val == current)
                group.addAction(a)
                a.triggered.connect(lambda _=False, k=key, x=val: self.action.emit(f"tableopt:{k}:{x}"))
            m.addSeparator()
        a = m.addAction("미리 보고 고치기…")
        a.triggered.connect(lambda: self.action.emit("table_preview"))
        q = m.addAction("표 버튼 누를 때마다 묻기")
        q.setCheckable(True)
        q.setChecked(not getattr(s, "table_quick", False))
        q.triggered.connect(lambda on: self.action.emit(f"tableopt:quick:{0 if on else 1}"))

    def table_menu(self, settings):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        self._fill_table_menu(m, settings)
        return m

    def pin_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        for key, label in (("pin", "찍은 자리에 그대로 (F3)"), ("pin_stack", "화면 오른쪽 위에 쌓기"),
                           ("pin_other", "다른 모니터로")):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, k=key: self.action.emit(k))
        m.addSeparator()
        a = m.addAction("고정한 캡처 관리…")
        a.triggered.connect(lambda: self.action.emit("pin_manager"))
        return m

    def search_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        a = m.addAction("내 캡처에서 찾기 — 저장 폴더의 캡처를 글자·태그·모양으로")
        a.triggered.connect(lambda _=False: self.action.emit("search_local"))
        m.addSeparator()
        head = m.addAction("그림으로 찾기 — 캡처가 저절로 붙습니다")
        head.setEnabled(False)
        for eng, label in (("google", "구글 렌즈 (그림으로 찾기)"),):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, e=eng: self.action.emit(f"search_img:{e}"))
        m.addSeparator()
        head2 = m.addAction("캡처 속 글자로 찾기")
        head2.setEnabled(False)
        for eng, label in (("google", "구글 검색"), ("naver", "네이버 검색"), ("papago", "파파고 번역")):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, e=eng: self.action.emit(f"search_text:{e}"))
        return m

    def _kakao_popup(self, btn) -> None:
        self.kakao_menu(self.kakao_provider()).exec(btn.mapToGlobal(btn.rect().topRight()))

    def _link_menu(self, btn) -> None:
        from PySide6.QtWidgets import QMenu
        if not edition.has_share():                        # work: the file link, nothing else
            self.action.emit("link_file")
            return
        m = QMenu(self)
        a = m.addAction("파일 링크 복사 — 저장한 위치 (인터넷에 올리지 않음)")
        a.triggered.connect(lambda: self.action.emit("link_file"))
        b = m.addAction("인터넷 공유 링크 만들기 — 누구나 열람, 정해진 시간 뒤 자동 삭제")
        b.triggered.connect(lambda: self.action.emit("link_web"))
        m.exec(btn.mapToGlobal(btn.rect().topRight()))
