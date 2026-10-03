"""Quick-action icons floating next to the captured region: copy, save as, OCR, send to PowerPoint, pin."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QToolButton, QWidget

from . import icons

ACTIONS = [
    ("copy", "copy", "복사", "클립보드에 복사 (Enter)"),
    ("save_as", "save_as", "저장", "저장 위치를 골라 저장 (Ctrl+Shift+S)"),
    ("text", "ocr", "텍스트", "이미지 속 글자를 인식해 복사"),
    ("ppt", "ppt", "PPT로", "캡처한 그대로 PowerPoint에 넣기 — 그림(그린 것 포함), 텍스트 모드에서는 글자"),
    ("ppt_shapes", "shapes", "도형PPT", "도형을 알아봐서 PowerPoint에서 고칠 수 있는 도형으로 넣기"),
    ("scroll", "scroll", "스크롤", "아래로 자동 스크롤하며 길게 캡처 — 브라우저 창 전체를 고르면 페이지 처음부터 끝까지 (Esc 중지)"),
    ("link", "link", "링크", "링크 복사 — ① 파일 링크: 저장한 파일 위치(인터넷에 올리지 않음, 같은 PC·공유 폴더에서 열림) "
                             "② 인터넷 공유 링크: 누구나 열 수 있는 주소, 정해진 시간 뒤 자동 삭제"),
    ("pin", "pin", "고정", "캡처를 다른 모든 창 위에 계속 떠 있게 붙여 둡니다 — 자료를 보며 작업할 때 (F3)"),
    ("kakao", "talk", "카톡", "카카오톡으로 보내기 — 열려 있는 채팅방을 고르면 그곳에 붙여 넣습니다 "
                              "(카카오톡의 [전송]을 눌러야 보내집니다)"),
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
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setSpacing(4)
        self.columns = 1
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
            if name == "link":
                b.clicked.connect(lambda _=False, btn=b: self._link_menu(btn))
            elif name == "kakao":
                b.clicked.connect(lambda _=False, btn=b: self._kakao_popup(btn))
            else:
                b.clicked.connect(lambda _=False, n=name: self.action.emit(n))
            self.buttons[name] = b
        self.set_columns(1)

    def set_columns(self, n: int) -> None:
        """One column normally; two when one column would be too tall for the screen."""
        self.columns = n
        for i, b in enumerate(self.buttons.values()):
            self._grid.removeWidget(b)
            self._grid.addWidget(b, i // n, i % n)
        self.adjustSize()

    def remove_action(self, name: str) -> None:
        b = self.buttons.pop(name, None)
        if b is not None:
            self._grid.removeWidget(b)
            b.hide()                       # gone right away, not only when Qt deletes it later
            b.setParent(None)
            b.deleteLater()
            self.set_columns(self.columns)

    def fit_height(self, max_height: int) -> None:
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
