"""Scroll capture from the capture UI: region scroll, whole-browser full page, stop, warnings."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.geometry import Rect
from capture_tool.core.settings import Settings
from capture_tool.platform.windows import WindowInfo
from tests.scrollsim import FakePage, make_page
from tests.test_app import FakeClipboard, FakeOcr, FakePpt, FakeScreen, decode_png, drag

VIEW = Rect(100, 50, 480, 400)          # the scrolling page area on screen
BROWSER = WindowInfo(11, "뉴스 - Chrome", Rect(90, 0, 500, 460))
NOTEPAD = WindowInfo(12, "메모장", Rect(90, 0, 500, 460))


class ScrollScreen(FakeScreen):
    def __init__(self, page: FakePage, wins=(BROWSER,), browsers=(11,), protected=None):
        super().__init__(wins=wins)
        self.page = page
        self.browsers = set(browsers)
        self.protected = dict(protected or {})
        self.wheel_at = []
        self.esc = []
        self.cursor_moves = []
        self.excluded = []
        self.roots = []

    def grab(self, r):
        if r.w == VIEW.w and r.h == VIEW.h and (r.x, r.y) == (VIEW.x, VIEW.y):
            self.grabs.append(r)
            return self.page.frame()
        return super().grab(r)

    def wheel(self, x, y, notches):
        self.wheel_at.append((x, y))
        self.page.wheel(notches)

    def set_cursor(self, x, y):
        self.cursor_moves.append((x, y))

    def esc_pressed(self):
        return self.esc.pop(0) if self.esc else False

    def display_affinity(self, hwnd):
        return self.protected.get(hwnd, 0)

    def is_browser(self, hwnd):
        return hwnd in self.browsers

    def browser_viewport(self, hwnd):
        return VIEW if hwnd in self.browsers else None

    def root_window_at(self, x, y):
        return self.roots.pop(0) if self.roots else 11

    def exclude_from_capture(self, hwnd):
        self.excluded.append(hwnd)
        return True


@pytest.fixture
def make(qt_app, tmp_path):
    from capture_tool.app.controller import Controller
    made = []

    def _make(screen, settings=None):
        c = Controller(screen=screen, clipboard=FakeClipboard(), ocr=FakeOcr(),
                       settings=settings or Settings(save_dir=str(tmp_path / "shots")),
                       settings_path=tmp_path / "settings.json", fallback_dir=tmp_path / "fallback", sync=True)
        c.ask_save_path = lambda default, parent=None: tmp_path / "scroll.png"
        made.append(c)
        return c
    yield _make
    for c in made:
        c.close_all()


def select_view(c):
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (VIEW.x, VIEW.y), (VIEW.x + VIEW.w, VIEW.y + VIEW.h))
    return ov


def pick_window(c, win):
    c.start_capture()
    ov = c.overlays[0]
    c.on_select_rect(win.rect, ov)
    return ov


def clip_img(c):
    return decode_png(c.clipboard.last[PNG])


def test_SAPP_01_region_scroll_from_where_it_is(make):
    fp = FakePage(make_page(1500), vh=400, start=200)
    scr = ScrollScreen(fp, wins=(NOTEPAD,), browsers=())
    c = make(scr)
    ov = select_view(c)
    ov.side_bar.trigger("scroll")
    assert not ov.isVisible()                            # the capture screen is out of the way
    assert c.overlays == [c.editor.canvas]               # ... and the result opens in the editor
    assert np.array_equal(clip_img(c), fp.expected(top=200))
    assert all(p == (VIEW.x + VIEW.w // 2, VIEW.y + VIEW.h // 2) for p in scr.wheel_at)
    assert any("스크롤 캡처" in m and "1300" in m for m in c.messages)


def test_SAPP_02_whole_browser_window_captures_the_full_page_from_the_top(make):
    fp = FakePage(make_page(1500), vh=400, start=700, header=0)
    scr = ScrollScreen(fp)
    c = make(scr)
    ov = pick_window(c, BROWSER)                         # click the browser window while selecting
    ov.side_bar.trigger("scroll")
    assert any(n > 0 for n in fp.wheels)                 # went to the top first
    img = clip_img(c)
    assert img.shape[:2] == (1500, 480)                  # page only: no tabs / address bar
    assert np.array_equal(img, fp.expected())
    assert any("페이지 전체" in m for m in c.messages)


def test_SAPP_03_whole_non_browser_window_scrolls_from_where_it_is(make):
    fp = FakePage(make_page(1500), vh=400, start=300)
    scr = ScrollScreen(fp, wins=(WindowInfo(12, "메모장", VIEW),), browsers=())
    c = make(scr)
    ov = pick_window(c, WindowInfo(12, "메모장", VIEW))
    ov.side_bar.trigger("scroll")
    assert all(n < 0 for n in fp.wheels)
    assert np.array_equal(clip_img(c), fp.expected(top=300))


def test_SAPP_04_escape_stops_and_keeps_the_part_captured(make):
    fp = FakePage(make_page(6000), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    scr.esc = [False] * 6 + [True]
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    img = clip_img(c)
    assert 400 < img.shape[0] < 6000 and np.array_equal(img, fp.expected()[:img.shape[0]])
    assert any("중지" in m for m in c.messages)


def test_SAPP_05_old_escape_press_does_not_stop_immediately(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    scr.esc = [True]                                    # Esc pressed before the scroll started
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    assert clip_img(c).shape[0] == 1500


def test_SAPP_06_not_scrollable_says_why(make):
    fp = FakePage(make_page(1500), vh=400, stuck=True)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    assert clip_img(c).shape[0] == 400
    assert any("스크롤되지 않" in m and "관리자" in m for m in c.messages)


def test_SAPP_07_too_long_page_is_cut_and_told(make):
    fp = FakePage(make_page(9000), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    c.scroll_limits = {"max_height": 3000}
    select_view(c).side_bar.trigger("scroll")
    assert clip_img(c).shape[0] == 3000
    assert any("3000" in m and "까지만" in m for m in c.messages)


def test_SAPP_08_protected_window_warns_that_it_comes_out_black(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(NOTEPAD,), browsers=(), protected={12: 0x1})
    c = make(scr)
    select_view(c)
    assert any("캡처 보호" in m and "메모장" in m and "검게" in m for m in c.messages)


def test_SAPP_09_protected_window_elsewhere_is_not_mentioned(make):
    fp = FakePage(make_page(1500), vh=400)
    far = WindowInfo(13, "은행", Rect(700, 500, 90, 90))
    scr = ScrollScreen(fp, wins=(far,), browsers=(), protected={13: 0x11})
    c = make(scr)
    select_view(c)
    assert not any("캡처 보호" in m for m in c.messages)


def test_SAPP_10_progress_window_is_hidden_from_the_capture(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    assert scr.excluded                                  # our "scrolling…" box is excluded
    assert c.scroll_indicator is None or not c.scroll_indicator.isVisible()


def test_SAPP_11_cursor_is_put_back(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    scr.cursor = (33, 44)
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    assert scr.cursor_moves[-1] == (33, 44)


def test_SAPP_12_result_opens_in_the_editor_with_save_and_ppt(make, tmp_path):
    from capture_tool.platform.powerpoint import Picture
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    c.powerpoint = FakePpt()
    select_view(c).side_bar.trigger("scroll")
    ed = c.editor
    assert ed is not None and ed.isVisible() and ed.canvas.image.shape[0] == 1500
    ed.canvas.side_bar.trigger("ppt")
    assert isinstance(c.powerpoint.items[-1], Picture) and c.powerpoint.items[-1].image.shape[0] == 1500
    select_view(c).side_bar.trigger("scroll")
    c.editor.canvas.side_bar.trigger("save_as")
    assert (tmp_path / "scroll.png").exists()
    select_view(c).side_bar.trigger("scroll")
    ed = c.editor
    QTest.keyClick(ed.canvas, Qt.Key_Escape)
    assert not ed.isVisible() and c.editor is None


def test_SAPP_13_drawings_are_not_part_of_a_scroll_capture_and_user_is_told(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    ov = select_view(c)
    ov.set_tool("rect")
    drag(ov, (150, 100), (250, 200))
    ov.side_bar.trigger("scroll")
    assert any("그린 내용" in m for m in c.messages)


def test_SAPP_14_scroll_hotkey_mode_starts_after_selecting(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    c.start_capture(mode="scroll")
    drag(c.overlays[0], (VIEW.x, VIEW.y), (VIEW.x + VIEW.w, VIEW.y + VIEW.h))
    assert clip_img(c).shape[0] == 1500


def test_SAPP_15_second_scroll_while_running_is_ignored(make):
    fp = FakePage(make_page(1500), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    c.scrolling = True
    ov = select_view(c)
    ov.side_bar.trigger("scroll")
    assert fp.wheels == [] and c.overlays                 # nothing started; capture still open


def test_SAPP_16_settings_and_hotkey_wiring():
    from capture_tool.app.hotkeys import IDS
    from capture_tool.app.settings_dialog import ACTIONS
    from capture_tool.core.settings import DEFAULT_HOTKEYS
    assert "scroll" in IDS and "scroll" in DEFAULT_HOTKEYS and "scroll" in dict(ACTIONS)


def test_SAPP_17_other_window_covering_stops_with_a_message(make):
    fp = FakePage(make_page(6000), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    scr.roots = [11, 11, 11, 11, 99]                   # a messenger window pops up over the page
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    img = clip_img(c)
    assert 400 <= img.shape[0] < 6000
    assert any("다른 창" in m for m in c.messages)


def test_SAPP_18_blocked_screen_capture_is_explained(make):
    fp = FakePage(make_page(3000), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    real = scr.page.frame
    scr.page.frame = lambda: np.full((400, 480, 3), 255, np.uint8) if fp.offset > 500 else real()
    c = make(scr)
    select_view(c).side_bar.trigger("scroll")
    assert any("막혔" in m and "보안" in m for m in c.messages)


def test_SAPP_19_whole_screen_blank_on_capture_start_is_explained(make):
    scr = FakeScreen(image=np.zeros((600, 800, 3), np.uint8))
    c = make(scr)
    c.start_capture()
    assert any("막혔" in m for m in c.messages)


def test_SAPP_20_browser_without_a_known_page_view_still_goes_from_the_top(make):
    fp = FakePage(make_page(1500), vh=400, start=600)
    scr = ScrollScreen(fp, wins=(WindowInfo(11, "Firefox", VIEW),))
    scr.browser_viewport = lambda hwnd: None               # e.g. Firefox: no Chromium page window
    c = make(scr)
    ov = pick_window(c, WindowInfo(11, "Firefox", VIEW))
    ov.side_bar.trigger("scroll")
    assert any(n > 0 for n in fp.wheels)
    assert np.array_equal(clip_img(c), fp.expected())
