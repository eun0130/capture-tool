"""Real Windows API tests (clipboard, monitors, capture, hotkeys, windows)."""
import sys
import threading
import time

import numpy as np
import pytest

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

from capture_tool.core.clipboard_payload import HTML, PNG, UNICODE, cf_html  # noqa: E402
from capture_tool.core.geometry import Rect, virtual_bounds  # noqa: E402
from capture_tool.core.hotkey import parse  # noqa: E402
from capture_tool.platform import screen, startup, win_clipboard, win_hotkey, windows  # noqa: E402

screen.set_dpi_awareness()


# --- clipboard ---------------------------------------------------------------

def test_WCLIP_01_multi_format_round_trip():
    html = cf_html("<b>한글</b>")
    win_clipboard.set_formats({UNICODE: "한글 text\r\n둘째", HTML: html, PNG: b"\x89PNGfake", "CaptureTool Test": b"xyz"})
    assert win_clipboard.get_text() == "한글 text\r\n둘째"
    assert win_clipboard.get_format(HTML).startswith(html)
    assert win_clipboard.get_format(PNG).startswith(b"\x89PNGfake")
    assert win_clipboard.get_format("CaptureTool Test").startswith(b"xyz")


_HOLDER = """
import ctypes, sys, time
from ctypes import wintypes
u32 = ctypes.WinDLL("user32")
u32.CreateWindowExW.restype = wintypes.HWND
u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
    wintypes.HINSTANCE, wintypes.LPVOID]
u32.OpenClipboard.argtypes = [wintypes.HWND]
hwnd = u32.CreateWindowExW(0, "STATIC", "holder", 0, 0, 0, 0, 0, None, None, None, None)
while not u32.OpenClipboard(hwnd):
    time.sleep(0.005)
print("held", flush=True)
time.sleep(float(sys.argv[1]))
u32.CloseClipboard()
"""


def _hold_clipboard(seconds):
    """Another process keeps the clipboard open, like a busy clipboard manager."""
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", _HOLDER, str(seconds)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def test_WCLIP_02_busy_clipboard_retries_then_succeeds():
    p = _hold_clipboard(0.15)
    win_clipboard.set_formats({UNICODE: "after wait"}, retries=50, delay=0.02)
    p.wait(5)
    assert win_clipboard.get_text() == "after wait"


def test_WCLIP_03_busy_clipboard_gives_up():
    p = _hold_clipboard(1.0)
    try:
        with pytest.raises(win_clipboard.ClipboardBusy):
            win_clipboard.set_formats({UNICODE: "x"}, retries=3, delay=0.02)
    finally:
        p.wait(5)


def test_WCLIP_04_empty_payload():
    with pytest.raises(ValueError):
        win_clipboard.set_formats({})


# --- monitors & capture ------------------------------------------------------

def test_WSCR_01_monitors():
    mons = screen.monitors()
    assert mons
    assert sum(1 for m in mons if m.primary) == 1
    assert all(m.rect.w > 0 and m.rect.h > 0 and m.scale >= 1.0 for m in mons)
    assert all(m.name for m in mons)


def test_WSCR_02_cursor_near_screens():
    x, y = screen.cursor_pos()
    vb = virtual_bounds(screen.monitors())
    assert vb.x - 1 <= x <= vb.right + 1 and vb.y - 1 <= y <= vb.bottom + 1


def test_WSCR_03_grab_region_shape():
    m = screen.monitors()[0]
    r = Rect(m.rect.x + 10, m.rect.y + 10, 120, 80)
    img = screen.grab(r)
    assert img.shape == (80, 120, 4) and img.dtype == np.uint8  # BGRA, zero-copy


def test_WSCR_04_grab_monitor_is_fast():
    m = screen.monitors()[0]
    screen.grab(m.rect)  # warm
    t = time.perf_counter()
    img = screen.grab(m.rect)
    elapsed = time.perf_counter() - t
    assert img.shape[:2] == (m.rect.h, m.rect.w)
    assert elapsed < 0.15, f"monitor grab took {elapsed * 1000:.0f} ms"


# --- hotkeys -----------------------------------------------------------------

def test_WHK_01_register_and_conflict():
    hk = parse("Ctrl+Alt+Shift+F24")
    assert win_hotkey.register(None, 0xB001, hk)
    try:
        assert not win_hotkey.register(None, 0xB002, hk)  # already taken -> conflict
    finally:
        win_hotkey.unregister(None, 0xB001)
    assert win_hotkey.register(None, 0xB003, hk)
    win_hotkey.unregister(None, 0xB003)


def test_WHK_02_default_hotkey_taken_is_explained():
    """If Win+~ is owned by another app (e.g. Windows Terminal quake mode), the app
    must be able to tell the user why."""
    hk = parse("Win+~")
    ok = win_hotkey.register(None, 0xB010, hk)
    if ok:
        win_hotkey.unregister(None, 0xB010)
    else:
        from capture_tool.core.hotkey import known_conflicts
        assert known_conflicts(hk)


# --- window auto-detect ------------------------------------------------------

def test_WWIN_01_top_level_windows():
    wins = windows.top_level_windows()
    assert isinstance(wins, list)
    for w in wins:
        assert w.rect.w > 0 and w.rect.h > 0
        assert isinstance(w.title, str)


def test_WWIN_02_window_at_prefers_topmost():
    a = windows.WindowInfo(1, "front", Rect(0, 0, 100, 100))
    b = windows.WindowInfo(2, "back", Rect(0, 0, 500, 500))
    assert windows.window_at((50, 50), [a, b]) is a
    assert windows.window_at((300, 300), [a, b]) is b
    assert windows.window_at((900, 900), [a, b]) is None


# --- PowerPoint automation ----------------------------------------------------

def _ppt_send(item):
    """Send into a brand-new deck, read what landed there, then close that deck unsaved."""
    pytest.importorskip("win32com.client")
    from capture_tool.platform import powerpoint
    if not powerpoint.installed():
        pytest.skip("PowerPoint not installed")
    seen = {}

    def hook(pres, slide, added):
        seen["shapes"] = [(s.Width, s.Height, s.TextFrame.TextRange.Text if s.HasTextFrame and s.TextFrame.HasText else "")
                          for s in slide.Shapes]
        pres.Saved = True
        pres.Close()

    r = powerpoint.send(item, new_presentation=True, hook=hook, timeout=30)
    return r, seen["shapes"]


@pytest.mark.slow
def test_WPPT_01_native_shapes_into_powerpoint():
    from capture_tool.core.clipboard_payload import GVML
    from capture_tool.core.drawingml import DConnector, DShape, gvml_package
    from capture_tool.platform.powerpoint import ClipboardShapes
    shapes = [DShape("roundRect", 20, 40, 150, 64, text="요청 접수"), DShape("roundRect", 240, 40, 150, 64, text="검토")]
    win_clipboard.set_formats({GVML: gvml_package(shapes, [DConnector(start=0, end=1)])})
    r, landed = _ppt_send(ClipboardShapes())
    assert r.added == 3
    assert [t for _, _, t in landed if t] == ["요청 접수", "검토"]


@pytest.mark.slow
def test_WPPT_02_picture_at_screen_size():
    from capture_tool.platform.powerpoint import Picture
    r, landed = _ppt_send(Picture(np.full((180, 300, 3), 200, np.uint8), dpi=144))
    assert r.added == 1 and [(round(w), round(h)) for w, h, _ in landed] == [(150, 90)]


@pytest.mark.slow
def test_WPPT_03_text_box():
    from capture_tool.platform.powerpoint import TextItem
    r, landed = _ppt_send(TextItem("견적 요약\n담당 홍길동"))
    assert r.added == 1 and landed[0][2] == "견적 요약\r담당 홍길동"


# --- startup (fake registry backend) -----------------------------------------

class FakeRun(dict):
    def set(self, name, value):
        self[name] = value

    def delete(self, name):
        self.pop(name, None)

    def get(self, name, default=None):
        return dict.get(self, name, default)


def test_WSTART_01_enable_disable():
    reg = FakeRun()
    startup.set_enabled(True, r"C:\Apps\CaptureTool\CaptureTool.exe", backend=reg)
    assert reg["CaptureTool"] == '"C:\\Apps\\CaptureTool\\CaptureTool.exe" --tray'
    assert startup.is_enabled(backend=reg)
    startup.set_enabled(False, "", backend=reg)
    assert not startup.is_enabled(backend=reg)
    startup.set_enabled(False, "", backend=reg)  # idempotent
