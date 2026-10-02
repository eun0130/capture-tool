"""Real desktop: one click captures a whole window across two monitors / off-screen / covered;
a real internet link (only with CAPTURE_TOOL_NET_TESTS=1: it uploads a test pattern)."""
import os
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]

PW = r'''
import sys, time
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
app = QApplication([])
from capture_tool.platform import windows, screen
def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
def colored(rgb, geo, frameless=False):
    w = QWidget(None, Qt.FramelessWindowHint if frameless else Qt.Window)
    w.setWindowTitle("PWTEST-%%d" %% rgb[0])
    pal = w.palette(); pal.setColor(QPalette.Window, QColor(*rgb)); w.setPalette(pal); w.setAutoFillBackground(True)
    w.setGeometry(*geo); w.show(); return w
red = colored((250, 20, 20), (300, 300, 500, 300))
pump(0.6)
blue = colored((20, 20, 250), (350, 350, 200, 150), frameless=True)   # covers part of red
blue.setWindowFlag(Qt.WindowStaysOnTopHint, True); blue.show()
pump(0.6)
win = next(w for w in windows.top_level_windows() if w.title == "PWTEST-250")
img = windows.capture_window(win.hwnd, win.rect)
mid = img[img.shape[0] // 2, img.shape[1] // 2] if img is not None else None
print("covered", None if img is None else img.shape[:2], win.rect.h, win.rect.w, None if mid is None else mid.tolist())
red.move(-250, 300); pump(0.8)                                         # partly off the screen
win = next(w for w in windows.top_level_windows() if w.title == "PWTEST-250")
img = windows.capture_window(win.hwnd, win.rect)
print("offscreen", None if img is None else img.shape[:2], win.rect.h, win.rect.w,
      None if img is None else img[img.shape[0] // 2, 20].tolist())
red.close(); blue.close(); pump(0.2)
'''


def _pw_ok(out: str) -> bool:
    lines = {l.split()[0]: l for l in out.splitlines() if l.startswith(("covered", "offscreen"))}
    if len(lines) != 2:
        return False
    for key in ("covered", "offscreen"):
        parts = lines[key].replace("(", "").replace(")", "").replace(",", " ").replace("[", " ").replace("]", " ").split()
        h, w, rh, rw = map(int, parts[1:5])
        b, g, r = map(int, parts[5:8])
        if (h, w) != (rh, rw) or not (r > 200 and b < 60):
            return False
    return True


def test_WWIN_REAL_01_window_picture_even_when_covered_or_off_screen(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(PW % ROOT, _pw_ok)
    assert _pw_ok(out), out


ACROSS = r'''
import sys, time, tempfile
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPalette, QColor, QGuiApplication
from PySide6.QtTest import QTest
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen, RealClipboard
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.settings import Settings
from capture_tool.core.clipboard_payload import PNG
from capture_tool.platform import win_clipboard
from tests.test_autosave_window_link import hover
import cv2, numpy as np
def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
screens = QGuiApplication.screens()
if len(screens) < 2:
    print("SKIP one monitor"); sys.exit(0)
a, b = sorted(screens, key=lambda s: s.geometry().x())[:2]
ga = a.geometry()
import subprocess
HELPER = """
import time
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
app = QApplication([])
w = QWidget(None, Qt.Window | Qt.WindowStaysOnTopHint); w.setWindowTitle('ACROSSTEST')
pal = w.palette(); pal.setColor(QPalette.Window, QColor(40, 160, 90)); w.setPalette(pal); w.setAutoFillBackground(True)
w.resize(520, 320)
w.show()
import ctypes
ctypes.windll.user32.SetWindowPos(int(w.winId()), 0, X, Y, 0, 0, 0x0001 | 0x0004)   # physical px
w.show()
end = time.time() + 25
while time.time() < end:
    app.processEvents(); time.sleep(0.02)
"""
from capture_tool.platform import screen as pscreen
mons = sorted(pscreen.monitors(), key=lambda m: m.rect.x)
edge = mons[1].rect.x                                                  # physical boundary between the monitors
helper = subprocess.Popen([sys.executable, "-c", HELPER.replace("X", str(edge - 300)).replace("Y", "200")])
from capture_tool.platform import windows as pw
target = None
for _ in range(150):                      # wait until it has moved onto the monitor boundary
    target = next((x for x in pw.top_level_windows() if x.title == "ACROSSTEST"), None)
    if target and target.rect.x < edge < target.rect.right:
        break
    time.sleep(0.1)
pump(0.8)
tmp = tempfile.mkdtemp(dir=r"%s")
c = Controller(RealScreen(), RealClipboard(), OcrEngine(), Settings(save_dir=tmp, auto_save=True),
               tmp + "/s.json", tmp, sync=True)
c.start_capture(); pump(0.4)
px = (target.rect.x + 60, target.rect.y + 12)                        # physical px, on the title bar
ov = next(o for o in c.overlays if o.monitor.rect.contains(px))
local = ov.to_local(*px).toPoint()
hover(ov, local)
print("label", ov.hover_label(), "rect", target.rect, [m.rect for m in c.screen.monitors()])
if "ACROSSTEST" not in ov.hover_label():
    print("SKIP another window is on top of the test window"); c.close_all(); helper.kill(); sys.exit(0)
QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, local); pump(0.5)
png = win_clipboard.get_format(PNG)
img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR) if png else None
import glob
wi = next(x for x in __import__("capture_tool.platform.windows", fromlist=["x"]).top_level_windows() if x.title == "ACROSSTEST") if False else None
print("result", None if img is None else img.shape[:2], "win", c.editor is not None and c.editor.isVisible(),
      "saved", len(glob.glob(tmp + "/*.png")),
      "center", None if img is None else img[img.shape[0] // 2, img.shape[1] // 2].tolist(),
      "right", None if img is None else img[img.shape[0] // 2, img.shape[1] - 30].tolist())
c.close_all(); helper.kill(); pump(0.2)
'''


def _across_ok(out: str) -> bool:
    if "SKIP" in out:
        return True
    line = next((l for l in out.splitlines() if l.startswith("result")), "")
    green = "[90, 160, 40]"
    return ("win True" in line and "saved 1" in line and line.count(green) == 2
            and "모니터" in out)


def test_WWIN_REAL_02_one_click_captures_a_window_across_two_monitors(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(ACROSS % (ROOT, tmp_path), _across_ok)
    if "SKIP" in out:
        pytest.skip(out.split("SKIP", 1)[1].strip().splitlines()[0])
    assert _across_ok(out), out


@pytest.mark.skipif(os.environ.get("CAPTURE_TOOL_NET_TESTS") != "1", reason="uploads a test pattern to the internet")
def test_WLINK_REAL_01_internet_link_opens_the_same_picture():
    import urllib.request
    import cv2
    import numpy as np
    from capture_tool.core.share import upload_litterbox
    img = np.zeros((64, 96, 3), np.uint8)
    img[:, :48] = (0, 128, 255)
    img[10:20, 60:90] = (255, 255, 255)
    ok, png = cv2.imencode(".png", img)
    url = upload_litterbox(png.tobytes(), "1h")
    assert url.startswith("https://litter.catbox.moe/")
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "CaptureTool"}), timeout=60).read()
    back = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert back is not None and np.array_equal(back, img)
