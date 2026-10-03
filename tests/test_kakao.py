"""Send a capture to KakaoTalk: the capture is copied, an open chat (or KakaoTalk itself) comes to
the front and the picture is pasted there - KakaoTalk then shows its own send confirmation,
so nothing is ever sent without the person pressing 전송."""
from capture_tool.core.clipboard_payload import PNG
from capture_tool.platform import kakao
from tests.test_app import drag, make  # noqa: F401 (fixture)


class FakeKakao:
    def __init__(self, installed=True, chats=((101, "승필"), (102, "클코단")), paste_ok=True, open_ok=True):
        self._installed, self._chats = installed, list(chats)
        self.paste_ok, self.open_ok = paste_ok, open_ok
        self.pasted, self.opened = [], 0

    def installed(self):
        return self._installed

    def chats(self):
        return list(self._chats)

    def open_main(self):
        self.opened += 1
        return self.open_ok

    def paste_into(self, hwnd):
        self.pasted.append(hwnd)
        return self.paste_ok and any(h == hwnd for h, _ in self._chats)


def capture(make, fake):
    c = make()
    c.kakao = fake
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    return c


def test_KAKAO_01_window_list_keeps_open_chats_only():
    wins = [(1, "EVA_Window_Dblclk", "카카오톡", True), (2, "EVA_Window_Dblclk", "승필", True),
            (3, "EVA_Window_Dblclk", "", True), (4, "EVA_Window_Dblclk", "숨은 방", False),
            (5, "tooltips_class32", "x", True), (6, "EVA_Window_Dblclk", "톡캘린더", True),
            (7, "EVA_Window_Dblclk", "브리핑 보드", True), (8, "EVA_Window_Dblclk", "📖 마음을 읽는 사람들", True)]
    assert kakao.main_window(wins) == 1
    assert kakao.chat_windows(wins) == [(2, "승필"), (8, "📖 마음을 읽는 사람들")]


def test_KAKAO_02_send_to_an_open_chat_copies_then_pastes_there(make):
    fake = FakeKakao()
    c = capture(make, fake)
    c.on_toolbar_action("kakao_chat:102")
    assert c.overlays == [] and PNG in c.clipboard.last
    assert fake.pasted == [102]
    assert any("클코단" in m and "전송" in m for m in c.messages)


def test_KAKAO_03_open_kakao_when_no_chat_is_chosen(make):
    fake = FakeKakao()
    c = capture(make, fake)
    c.on_toolbar_action("kakao_main")
    assert fake.opened == 1 and fake.pasted == [] and PNG in c.clipboard.last
    assert any("채팅방" in m and "Ctrl+V" in m for m in c.messages)


def test_KAKAO_04_not_installed_keeps_the_copy_and_says_so(make):
    fake = FakeKakao(installed=False)
    c = capture(make, fake)
    c.on_toolbar_action("kakao_main")
    assert fake.opened == 0 and PNG in c.clipboard.last
    assert any("설치되어 있지 않" in m for m in c.messages)


def test_KAKAO_05_chat_closed_meanwhile_falls_back_to_kakao(make):
    fake = FakeKakao(chats=())
    c = capture(make, fake)
    c.on_toolbar_action("kakao_chat:555")
    assert fake.opened == 1
    assert any("채팅방" in m for m in c.messages)


def test_KAKAO_06_paste_not_confirmed_tells_how(make):
    fake = FakeKakao(paste_ok=False)
    c = capture(make, fake)
    c.on_toolbar_action("kakao_chat:101")
    assert any("Ctrl+V" in m for m in c.messages)


def test_KAKAO_07_side_bar_menu_lists_chats_and_open(qt_app):
    from capture_tool.app.side_bar import SideBar
    bar = SideBar()
    seen = []
    bar.action.connect(seen.append)
    menu = bar.kakao_menu(FakeKakao())
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("승필" in t for t in texts) and any("클코단" in t for t in texts) and any("열기" in t for t in texts)
    next(a for a in menu.actions() if "클코단" in a.text()).trigger()
    assert seen == ["kakao_chat:102"]
    empty = bar.kakao_menu(FakeKakao(installed=False))
    assert any("설치" in a.text() for a in empty.actions())


def test_KAKAO_08_bad_action_text_is_ignored(make):
    fake = FakeKakao()
    c = capture(make, fake)
    c.on_toolbar_action("kakao_chat:abc")
    assert fake.pasted == [] and c.overlays                    # nothing done, capture still open


def test_KAKAO_09_works_from_the_edit_window_too(make):
    import numpy as np
    fake = FakeKakao()
    c = make()
    c.kakao = fake
    c.open_editor(np.full((3000, 800, 3), 200, np.uint8), 96, "스크롤 캡처")
    c.editor.canvas.side_bar.trigger("kakao_chat:101")
    assert PNG in c.clipboard.last and fake.pasted == [101]
