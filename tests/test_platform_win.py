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



@pytest.mark.slow
def test_WPPT_04_new_slide_after_the_viewed_slide_in_an_open_deck():
    """Real PowerPoint: my own 3-slide deck, viewing slide 2 -> the picture lands on a new
    slide 3, slides 1-3 before stay empty. Only the test's own deck is touched and closed."""
    pytest.importorskip("win32com.client")
    import pythoncom
    import win32com.client
    from capture_tool.platform import powerpoint
    from capture_tool.platform.powerpoint import Picture
    if not powerpoint.installed():
        pytest.skip("PowerPoint not installed")
    pythoncom.CoInitialize()
    app = win32com.client.Dispatch("PowerPoint.Application")
    app.Visible = True
    mine = app.Presentations.Add()
    my_name = mine.Name

    class OnlyMyDeck:
        """The real PowerPoint, but "active" deck/window are always the test's own deck, so a
        document the person is working on in PowerPoint at the same time is never touched."""

        def __init__(self):
            pythoncom.CoInitialize()                 # send() runs this in its own worker thread
            self._app = win32com.client.Dispatch("PowerPoint.Application")   # this thread's proxy
            self.Presentations = self._app.Presentations
            self.ActivePresentation = next(p for p in self._app.Presentations if p.Name == my_name)
            self.ActiveWindow = self.ActivePresentation.Windows(1)

        def __setattr__(self, k, v):
            if k == "Visible":
                return
            object.__setattr__(self, k, v)

        def Activate(self):
            pass
    try:
        for i in range(3):
            mine.Slides.Add(i + 1, 12)
        mine.Windows(1).View.GotoSlide(2)
        seen = {}

        def hook(pres, slide, added):
            seen["mine"] = pres.Name == my_name   # COM objects can't cross threads: compare names
            seen["index"] = slide.SlideIndex
        img = np.full((120, 200, 4), 200, np.uint8)
        img[:40, :40] = (255, 255, 255, 0)            # a freeform-crop style transparent corner
        r = powerpoint.send(Picture(img), app_factory=OnlyMyDeck, hook=hook, timeout=30, new_slide=True)
        assert seen == {"mine": True, "index": 3} and r.added == 1
        assert mine.Slides.Count == 4
        assert [mine.Slides(i).Shapes.Count for i in (1, 2, 3, 4)] == [0, 0, 1, 0]
    finally:
        mine.Saved = True
        mine.Close()


def test_PWIN_30_a_korean_folder_gets_an_english_path_to_the_same_files(tmp_path):
    """BUG-141: the AI engine could not open its model under C:\\Users\\<Korean name>. ascii_path gives
    an English-only path (short name or a folder link under Public) that reaches the same file."""
    import os
    import shutil
    from capture_tool.platform import shell
    d = tmp_path / "홍길동 모델"
    d.mkdir()
    (d / "genai_config.json").write_text('{"model": {}}', encoding="utf-8")
    p = shell.ascii_path(d)
    try:
        assert p.isascii(), p
        with open(os.path.join(p, "genai_config.json"), "rb") as f:     # a narrow-string open, like the engine
            assert f.read() == b'{"model": {}}'
    finally:
        if "Public" in p:
            os.rmdir(p)                                                     # the link only, never the folder
        shutil.rmtree(d, ignore_errors=True)


def test_PWIN_31_the_ai_engine_opens_its_config_through_the_english_path(tmp_path):
    """BUG-141 on real Windows with the real engine: onnxruntime-genai reads the summary model's own
    genai_config.json (tests/data, the pinned file) from a folder with Korean letters through ascii_path.
    What the plain Korean path does is printed for the record (the cause)."""
    import os
    import shutil
    from pathlib import Path
    og = pytest.importorskip("onnxruntime_genai")
    from capture_tool.platform import shell
    d = tmp_path / "홍길동 모델"
    d.mkdir()
    shutil.copy(Path(__file__).parent / "data" / "genai_config_qwen3.json", d / "genai_config.json")
    try:
        og.Config(str(d))
        print("KOREAN_PATH ok")
    except Exception as e:  # noqa: BLE001 - recorded, not asserted
        print("KOREAN_PATH failed:", e)
    p = shell.ascii_path(d)
    try:
        assert p.isascii(), p
        assert og.Config(p) is not None
        print("ASCII_PATH ok:", p)
    finally:
        if "Public" in p:
            os.rmdir(p)                                                     # the link only
        shutil.rmtree(d, ignore_errors=True)


DXGI_FLOW = r"""
import sys, time
sys.path.insert(0, r"%s")
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
from capture_tool.core.geometry import Rect
from capture_tool.platform import screen
screen.set_dpi_awareness()


class Halves(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(0, 0, 100, 100, QColor(255, 0, 0))      # red left
        p.fillRect(100, 0, 100, 100, QColor(0, 0, 255))    # blue right
        p.end()


w = Halves(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
w.setGeometry(120, 120, 200, 100)
w.show()
for _ in range(40):
    app.processEvents()
    time.sleep(0.03)
k = w.devicePixelRatioF()
g = w.geometry()
r = Rect(int(g.x() * k), int(g.y() * k), int(200 * k), int(100 * k))
try:
    dx = screen._dxgi_grab(r)
except Exception as e:
    print("DXGI_ERROR", type(e).__name__, e)
    dx = None
print("DXGI", None if dx is None else tuple(dx.shape))
if dx is not None:
    print("LEFT", dx[int(50 * k), int(50 * k)][:3].tolist(), "RIGHT", dx[int(50 * k), int(150 * k)][:3].tolist())
f = screen.grab_frame(r)
print("FRAME", tuple(f.shape), "LEFTF", f[int(50 * k), int(50 * k)][:3].tolist())
"""


def test_PWIN_32_the_dxgi_still_frame_reads_the_right_place_in_the_right_colours():
    """BUG-142: the capture screen's still picture comes through DXGI desktop duplication. A window of a
    red and a blue half: DXGI must see it where it is, in BGR order like the GDI grab."""
    from pathlib import Path
    from tests.conftest import run_on_desktop
    out = run_on_desktop(DXGI_FLOW % Path(__file__).resolve().parents[1], lambda o: "FRAME" in o, attempts=1)
    print(out)
    if "DXGI None" in out:
        pytest.skip("DXGI desktop duplication not available here: " + out.strip()[-200:])
    assert "LEFT [0, 0, 255]" in out and "RIGHT [255, 0, 0]" in out, out          # BGR: red, blue
    assert "LEFTF [0, 0, 255]" in out, out                                        # grab_frame took it


def _mp4_tracks(path):
    """(handler types of the tracks, duration in s) read from the MP4 boxes themselves."""
    import struct
    data = open(path, "rb").read()
    handlers, duration = [], None

    def walk(start, end):
        nonlocal duration
        i = start
        while i + 8 <= end:
            size, kind = struct.unpack(">I4s", data[i:i + 8])
            if size < 8:
                break
            if kind in (b"moov", b"trak", b"mdia"):
                walk(i + 8, i + size)
            elif kind == b"mvhd":
                v = data[i + 8]
                if v == 0:
                    scale, dur = struct.unpack(">II", data[i + 20:i + 28])
                else:
                    scale, dur = struct.unpack(">IQ", data[i + 28:i + 40])
                duration = dur / scale
            elif kind == b"hdlr":
                handlers.append(data[i + 16:i + 20].decode("ascii"))
            i += size
    walk(0, len(data))
    return handlers, duration


def test_PWIN_33_media_foundation_writes_an_mp4_with_picture_and_sound(tmp_path):
    """Screen recording on Windows: H.264 + AAC through Media Foundation's Sink Writer (Windows'
    own encoder, no GPL). Frames with a red top and a blue bottom half (the picture must not come out
    upside down), a 440 Hz tone; read back: frames, orientation, both tracks, the length."""
    import cv2
    from capture_tool.platform import mf_recorder
    out = tmp_path / "rec.mp4"
    W, H, FPS = 320, 240, 15
    try:
        w = mf_recorder.open_writer(out, W, H, FPS, {"rate": 48000, "channels": 2})
    except OSError as e:
        pytest.skip(f"Media Foundation not usable here: {e}")
    img = np.zeros((H, W, 4), np.uint8)
    img[: H // 2, :, 2] = 255                                   # red top (B, G, R, A)
    img[H // 2:, :, 0] = 255                                    # blue bottom
    img[..., 3] = 255
    for i in range(30):
        w.add_frame(img, i / FPS)
    tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(2 * 48000) / 48000)).astype(np.float32)
    pcm = np.stack([tone, tone], axis=1)
    for k in range(0, len(pcm), 4800):
        w.add_audio(pcm[k:k + 4800], k / 48000)
    w.close()
    cap = cv2.VideoCapture(str(out))
    frames, first = 0, None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames += 1
        first = f if first is None else first
    print("FRAMES", frames, None if first is None else first.shape)
    handlers, duration = _mp4_tracks(out)
    print("TRACKS", handlers, "DURATION", duration)
    assert frames >= 28 and first.shape == (H, W, 3)
    top, bottom = first[H // 4, W // 2], first[3 * H // 4, W // 2]
    print("TOP", top.tolist(), "BOTTOM", bottom.tolist())
    assert top[2] > 200 and top[0] < 60 and bottom[0] > 200 and bottom[2] < 60        # red over blue
    assert sorted(handlers) == ["soun", "vide"] and abs(duration - 2.0) < 0.2


def test_PWIN_34_microphone_and_computer_sound_come_through_soundcard():
    """Screen recording's sound on Windows (WASAPI through soundcard). A PC without sound devices
    (a build server) skips; a silent computer may give no loopback blocks at all - only errors fail."""
    import time
    from capture_tool.platform import win_audio
    try:
        import soundcard
        soundcard.default_microphone()
        soundcard.default_speaker()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no sound devices here: {e}")
    got = {"mic": [], "system": []}
    srcs = win_audio.sources(mic=True, system=True)
    for s in srcs:
        s.start(lambda block, rate, n=s.name: got[n].append((block.shape, rate)))
    time.sleep(1.0)
    for s in srcs:
        s.stop()
    print("MIC", len(got["mic"]), "SYSTEM", len(got["system"]), [s.error for s in srcs])
    assert all(s.error is None for s in srcs), [s.error for s in srcs]
    assert got["mic"] and all(r == 48000 and sh[1] == 2 for sh, r in got["mic"])


def test_PWIN_35_a_recording_goes_on_the_clipboard_as_a_file_explorer_can_paste(tmp_path):
    import ctypes
    from ctypes import wintypes
    from capture_tool.core.clipboard_payload import files_payload
    f = tmp_path / "녹화 1.mp4"
    f.write_bytes(b"x")
    win_clipboard.set_formats(files_payload([f]), retries=10, delay=0.05)
    u32, sh = ctypes.WinDLL("user32"), ctypes.WinDLL("shell32")
    u32.GetClipboardData.restype = wintypes.HANDLE
    sh.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    assert u32.OpenClipboard(None)
    try:
        h = u32.GetClipboardData(15)                                   # CF_HDROP
        assert h, "no file on the clipboard"
        count = sh.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
        buf = ctypes.create_unicode_buffer(1024)
        sh.DragQueryFileW(h, 0, buf, 1024)
    finally:
        u32.CloseClipboard()
    assert count == 1 and buf.value == str(f)
