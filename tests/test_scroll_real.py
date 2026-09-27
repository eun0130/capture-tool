"""Real desktop: scroll capture with real wheel input and real screen grabs, a real browser page,
and how capture-protected windows behave."""
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

ROOT = Path(__file__).resolve().parents[1]

QT_SCROLL = r'''
import sys, time
sys.path.insert(0, r"%s")
import numpy as np
from PySide6.QtWidgets import QApplication, QScrollArea, QLabel
from PySide6.QtCore import Qt
app = QApplication([])
from capture_tool.app.render import bgr_to_pixmap
from capture_tool.core.geometry import Rect
from capture_tool.core.scroll_session import ScrollCapture
from capture_tool.platform import screen, scroll
from tests.scrollsim import make_page
area = QScrollArea()
area.setWindowFlags(Qt.WindowStaysOnTopHint)
area.setGeometry(120, 120, 560, 420)
area.show()
dpr = area.devicePixelRatioF()
page = make_page(int(1800 * dpr), w=int(500 * dpr), seed=7)
lab = QLabel()
lab.setPixmap(bgr_to_pixmap(page, dpr))
lab.resize(round(page.shape[1] / dpr), round(page.shape[0] / dpr))
area.setWidget(lab)
def pump(ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        app.processEvents(); time.sleep(0.005)
pump(600)
vp = area.viewport()
g = vp.mapToGlobal(vp.rect().topLeft())
x, y = round(g.x() * dpr), round(g.y() * dpr)
w = min(round(vp.width() * dpr), page.shape[1])
r = Rect(x, y, w, round(vp.height() * dpr))
old = screen.cursor_pos()
sc = ScrollCapture(grab=lambda: screen.grab(r), wheel=lambda n: scroll.wheel(x + w // 2, y + r.h // 2, n))
for ms in sc.run():
    pump(ms)
scroll.set_cursor(*old)
out = sc.result()
exp = page[:, :out.shape[1]]
same = out.shape == exp.shape and np.array_equal(out, exp)
print("RESULT", sc.reason, out.shape, exp.shape, "exact" if same else "diff")
'''


def _qt_ok(out: str) -> bool:
    return "RESULT end" in out and "exact" in out


def test_WSCR_01_real_wheel_and_grab_rebuild_a_scrolled_window_exactly(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(QT_SCROLL % ROOT, _qt_ok)
    assert _qt_ok(out), out


HTML = """<!doctype html><html><head><meta charset="utf-8"><title>SCROLLTEST-%s</title>
<style>body{margin:0;font:32px sans-serif}
#hd{position:sticky;top:0;height:60px;background:#1c64d8;color:#fff}
.s{height:150px;display:flex;align-items:center;padding-left:40px}
#ft{height:80px;background:#e03131}</style></head><body>
<div id="hd">STICKY HEADER</div>%s<div id="ft"></div></body></html>"""
COLORS = ["#%02x%02x%02x" % (40 + (i * 53) % 200, 60 + (i * 97) % 180, 80 + (i * 29) % 160) for i in range(30)]


def _browser():
    for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",   # fresh Chrome profile: no dialogs
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
        if os.path.exists(p):
            return p
    return None


def _runs(col: np.ndarray) -> list[tuple[int, int, int]]:
    """Distinct solid colors down a pixel column, in order (merging repeats)."""
    out = []
    for px in col:
        c = tuple(int(v) for v in px)
        if not out or max(abs(a - b) for a, b in zip(out[-1], c)) > 6:
            out.append(c)
    return out


def test_WSCR_02_real_browser_whole_page_from_the_top(tmp_path):
    from capture_tool.platform import screen, scroll, windows
    from capture_tool.core.scroll_session import ScrollCapture
    exe = _browser()
    if exe is None:
        pytest.skip("no Chromium browser")
    screen.set_dpi_awareness()
    tag = str(os.getpid())
    body = "".join(f'<div class="s" style="background:{c}">SECTION {i}</div>' for i, c in enumerate(COLORS))
    html = tmp_path / "page.html"
    html.write_text(HTML % (tag, body), encoding="utf-8")
    proc = subprocess.Popen([exe, f"--user-data-dir={tmp_path / 'profile'}", "--no-first-run",
                             "--no-default-browser-check", "--disable-sync", "--new-window", "--window-position=80,40",
                             "--window-size=900,760", html.as_uri()])
    try:
        win = None
        for _ in range(100):
            win = next((w for w in windows.top_level_windows() if f"SCROLLTEST-{tag}" in w.title), None)
            if win:
                break
            time.sleep(0.2)
        if not win:
            pytest.skip("the browser did not open a window (desktop / network busy)")
        import ctypes
        from ctypes import wintypes
        fg = ctypes.WinDLL("user32").SetForegroundWindow
        fg.argtypes = [wintypes.HWND]
        fg(win.hwnd)                                              # the page must be on top to be seen
        time.sleep(1.5)
        assert scroll.is_browser(win.hwnd)
        vp = None
        for _ in range(25):                                        # the page view appears once loaded
            vp = scroll.browser_viewport(win.hwnd)
            if vp:
                break
            time.sleep(0.2)
        assert vp and vp.w < win.rect.w + 1 and vp.h < win.rect.h      # page area only
        cx, cy = vp.x + vp.w // 2, vp.y + vp.h // 2
        old = screen.cursor_pos()
        for _attempt in range(3):   # the person may be using the PC: another window can pop up
            fg(win.hwnd)
            time.sleep(0.5)
            scroll.wheel(cx, cy, -6)                                     # start somewhere in the middle
            time.sleep(0.5)
            sc = ScrollCapture(grab=lambda: screen.grab(vp), wheel=lambda n: scroll.wheel(cx, cy, n), to_top=True,
                               still_visible=lambda: scroll.root_window_at(cx, cy) == win.hwnd)
            for ms in sc.run():
                time.sleep(ms / 1000)
            if sc.reason not in ("covered", "blocked"):
                break
            time.sleep(3)
        scroll.set_cursor(*old)
        if sc.reason in ("covered", "blocked"):
            pytest.skip(f"desktop in use: {sc.reason}")        # another window / blanked screen grabs
        out = sc.result()
        import cv2
        cv2.imwrite(str(tmp_path / "result.png"), out)     # test page only (fresh browser profile)
        colors = _runs(out[:, int(out.shape[1] * 0.8)])        # right side: no text there
        def near(c, hexc):
            h = hexc.lstrip("#")
            b, g, r = int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)
            return max(abs(c[0] - b), abs(c[1] - g), abs(c[2] - r)) <= 8
        seq = [i for c in colors for i, hc in enumerate(COLORS) if near(c, hc)]
        assert sc.reason == "end", sc.reason
        assert near(colors[0], "#1c64d8")                     # header on top, once
        assert sum(near(c, "#1c64d8") for c in colors) == 1
        assert seq == list(range(len(COLORS))), seq           # every section once, in order
        assert near(colors[-1], "#e03131")                   # page footer at the end
    finally:
        # only the browser processes of THIS test's own profile (Chrome hands off to children)
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        marker = str(tmp_path / "profile").replace("'", "''")
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
                        f"$_.CommandLine.Contains('{marker}') }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force "
                        "-ErrorAction SilentlyContinue }"], capture_output=True)


PROTECT = r'''
import sys, time, ctypes
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
app = QApplication([])
from capture_tool.core.geometry import Rect
from capture_tool.platform import screen, scroll
w = QWidget(None, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
pal = w.palette(); pal.setColor(QPalette.Window, QColor(255, 0, 0)); w.setPalette(pal); w.setAutoFillBackground(True)
w.setGeometry(300, 300, 300, 200); w.show()
def pump():
    for _ in range(20):
        app.processEvents(); time.sleep(0.02)
pump()
hwnd = int(w.winId()); s = w.devicePixelRatioF()
r = Rect(round(330 * s), round(330 * s), 40, 40)
def red():
    return int(screen.grab(r)[:, :, 2].mean())
print("plain", scroll.display_affinity(hwnd), red())
ctypes.WinDLL("user32").SetWindowDisplayAffinity(hwnd, 1); pump()
print("monitor", scroll.display_affinity(hwnd), red())
scroll.exclude_from_capture(hwnd); pump()
print("exclude", scroll.display_affinity(hwnd), red())
print("proc", scroll.process_name(hwnd), scroll.is_browser(hwnd), scroll.browser_viewport(hwnd))
'''


def _protect_ok(out: str) -> bool:
    return ("plain 0 255" in out and "monitor 1 0" in out and "exclude 17 " in out
            and "proc python.exe False None" in out)


def test_WSCR_03_capture_protected_windows_come_out_black_and_are_detected(tmp_path):
    """SetWindowDisplayAffinity: Windows itself blanks the window in every screenshot.
    The tool can see the flag (to explain it) but never gets the pixels."""
    from tests.conftest import run_on_desktop
    out = run_on_desktop(PROTECT % ROOT, _protect_ok)
    assert _protect_ok(out), out
