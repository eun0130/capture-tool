"""Quick-action icons floating next to the captured region: copy, save as, OCR, send to PowerPoint, pin."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QToolButton, QWidget

from . import icons

# (action, icon, label, tooltip, row): "basic" = the one-row bar, "extra" = shown under 전체
ACTIONS = [
    ("copy", "copy", "복사", "클립보드에 복사하고 닫기 (Enter · Ctrl+C) — 영역을 고르면 이미 복사되어 있습니다", "basic"),
    ("autosave", "save", "자동저장", "켜 두면 캡처를 끝낼 때마다 저장 폴더에 파일로도 저장 (누를 때마다 켜기/끄기)", "basic"),
    ("text", "ocr", "텍스트", "이미지 속 글자를 인식해 복사", "basic"),
    ("table", "table", "표", "캡처 속 표를 칸 그대로 복사 — 엑셀·PowerPoint에 붙이면 고칠 수 있는 표", "basic"),
    ("ppt", "ppt", "PPT", "캡처한 그대로 PowerPoint에 넣기 — 그림(그린 것 포함), 텍스트 모드에서는 글자", "basic"),
    ("mail", "mail", "메일", "메일로 보내기 — 받는 사람을 고르면 네이버·Gmail 등의 쓰기 화면이 열리고, 도우미 창으로 붙여 넣기 "
                             "([보내기]는 직접)", "basic"),
    ("kakao", "talk", "카톡", "카카오톡으로 보내기 — 열려 있는 채팅방을 고르면 그곳에 붙여 넣습니다 "
                              "(카카오톡의 [전송]을 눌러야 보내집니다)", "basic"),
    ("search", "search", "검색", "검색 — 그림으로 찾기(구글·네이버, 검색창에 Ctrl+V) 또는 캡처 속 글자로 찾기(구글·네이버·파파고)",
     "basic"),
    ("pin", "pin", "고정", "캡처를 다른 모든 창 위에 계속 떠 있게 붙여 둡니다 — 여러 장 가능 (F3)", "basic"),
    ("more", "more", "전체", "모든 기능 펼치기 / 기본만 보기 (마지막 상태를 기억)", "basic"),
    ("save_as", "save_as", "다른 이름 저장", "저장 위치를 골라 저장 (Ctrl+Shift+S)", "extra"),
    ("ppt_shapes", "shapes", "도형PPT", "도형을 알아봐서 PowerPoint에서 고칠 수 있는 도형으로 넣기", "extra"),
    ("scroll", "scroll", "스크롤", "아래로 자동 스크롤하며 길게 캡처 — 브라우저 창 전체를 고르면 페이지 처음부터 끝까지 (Esc 중지)",
     "extra"),
    ("link", "link", "링크", "링크 복사 — ① 파일 링크: 저장한 파일 위치(인터넷에 올리지 않음, 같은 PC·공유 폴더에서 열림) "
                             "② 인터넷 공유 링크: 누구나 열 수 있는 주소, 정해진 시간 뒤 자동 삭제", "extra"),
    ("open_folder", "folder", "저장 폴더", "저장 폴더 열기", "extra"),
    ("help", "help", "도움말", "처음 쓰는 분을 위한 따라하기 설명서 (F1)", "extra"),
]

INK = "#E9ECF2"                  # icon and label colour on the dark bar
# groups shown with a thin divider between them in the one-row bar
GROUPS = [("copy", "autosave"), ("text", "table", "ppt"), ("mail", "kakao", "search"), ("pin",), ("more",)]

STYLE = """
QWidget#sidebar { background: #1B1F2A; border: 1px solid #353C4E; border-radius: 16px; }
QToolButton { border: none; border-radius: 10px; color: #E9ECF2; font-size: 11px; padding: 4px 1px; }
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
QMenu { background: #1F2430; color: #E9ECF2; border: 1px solid #353C4E; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: #2F3B55; }
QMenu::item:disabled { color: #8A93A6; }
QMenu::indicator { width: 14px; height: 14px; left: 4px; }
QMenu::separator { height: 1px; background: #353C4E; margin: 5px 8px; }
"""


class SideBar(QWidget):
    """Quick actions for the capture. Row mode (default): one row of the common actions under
    the capture, a second row with the rest when expanded (전체). Column mode: everything in a
    column (the edit window's right side)."""
    action = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(4)
        self._extra = QWidget(self)               # second row: its own spacing, not the first row's columns
        self._extra_row = QHBoxLayout(self._extra)
        self._extra_row.setContentsMargins(0, 0, 0, 0)
        self._extra_row.setSpacing(4)
        self.columns = 0                  # 0 = row mode
        self.expanded = False
        self.buttons: dict[str, QToolButton] = {}
        self._row: dict[str, str] = {}
        self._dividers: list[QFrame] = []
        for name, icon_name, label, tip, row in ACTIONS:
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
            elif name == "pin":
                b.clicked.connect(lambda _=False, btn=b: self.pin_menu().exec(btn.mapToGlobal(btn.rect().bottomLeft())))
            elif name == "search":
                b.clicked.connect(lambda _=False, btn=b: self.search_menu().exec(btn.mapToGlobal(btn.rect().bottomLeft())))
            else:
                b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            self.buttons[name] = b
            self._row[name] = row
        self._arrange()

    def _arrange(self) -> None:
        for b in self.buttons.values():
            self._grid.removeWidget(b)
            self._extra_row.removeWidget(b)
        self._grid.removeWidget(self._extra)
        for d in self._dividers:
            self._grid.removeWidget(d)
            d.hide()                                  # gone now, not when Qt deletes it later
            d.deleteLater()
        self._dividers = []
        while self._extra_row.count():
            self._extra_row.takeAt(0)
        if self.columns:
            self._extra.hide()                  # column: everything but the row-only switches
            names = [n for n in self.buttons if n not in ("more", "autosave")]
            for i, n in enumerate(names):
                b = self.buttons[n]
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setFixedSize(QSize(64, 54))
                self._grid.addWidget(b, i // self.columns, i % self.columns)
                b.setVisible(True)
            for n in ("more", "autosave"):
                if n in self.buttons:
                    self.buttons[n].setVisible(False)
        else:
            basic = [n for n in self.buttons if self._row[n] == "basic"]
            extra = [n for n in self.buttons if self._row[n] == "extra"]
            col, group = 0, None
            for n in basic:
                g = next((k for k, names in enumerate(GROUPS) if n in names), None)
                if group is not None and g != group:          # a thin line between groups
                    d = QFrame(self)
                    d.setObjectName("divider")
                    d.setFixedSize(1, 22)
                    self._grid.addWidget(d, 0, col, Qt.AlignVCenter)
                    d.show()
                    self._dividers.append(d)
                    col += 1
                group = g
                b = self.buttons[n]
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                b.setMinimumSize(QSize(0, 40))
                b.setMaximumSize(QSize(16777215, 40))
                b.setVisible(True)
                self._grid.addWidget(b, 0, col)
                col += 1
            for n in extra:
                b = self.buttons[n]
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                b.setMinimumSize(QSize(0, 40))
                b.setMaximumSize(QSize(16777215, 40))
                self._extra_row.addWidget(b)
                b.setVisible(self.expanded)
            self._extra_row.addStretch(1)
            self._grid.addWidget(self._extra, 1, 0, 1, max(1, col))
            self._extra.setVisible(self.expanded)
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
            self.adjustSize()

    def remove_action(self, name: str) -> None:
        b = self.buttons.pop(name, None)
        if b is not None:
            self._grid.removeWidget(b)
            b.hide()                       # gone right away, not only when Qt deletes it later
            b.setParent(None)
            b.deleteLater()
            self._arrange()

    def fit_height(self, max_height: int) -> None:
        """Column mode only: two columns when one would be too tall for the screen."""
        if not self.columns:
            return
        one = len(self.buttons) * 58 + 12
        want = 1 if one <= max_height else 2
        if want != self.columns:
            self.set_columns(want)

    def trigger(self, name: str) -> None:
        self.action.emit(name)

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
        m = QMenu(self)
        a = m.addAction("파일 링크 복사 — 저장한 위치 (인터넷에 올리지 않음)")
        a.triggered.connect(lambda: self.action.emit("link_file"))
        b = m.addAction("인터넷 공유 링크 만들기 — 누구나 열람, 정해진 시간 뒤 자동 삭제")
        b.triggered.connect(lambda: self.action.emit("link_web"))
        m.exec(btn.mapToGlobal(btn.rect().topRight()))
