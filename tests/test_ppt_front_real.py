"""Real PowerPoint: after inserting, PowerPoint is the active window in front, showing the new
slide with the inserted object selected. Uses a presentation the test creates and closes."""
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]

FLOW = r'''
import sys, time, ctypes
from ctypes import wintypes
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt
app = QApplication([])
import numpy as np
from capture_tool.platform import powerpoint
from capture_tool.platform.powerpoint import Picture, send, bring_to_front
if not powerpoint.installed():
    print("SKIP no PowerPoint"); sys.exit(0)
u32 = ctypes.WinDLL("user32"); u32.GetForegroundWindow.restype = wintypes.HWND
def pump(s):
    end = time.time() + s
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
w = QWidget(None, Qt.Window); w.setWindowTitle("FRONTTEST capture tool"); w.resize(400, 300); w.show()
w.raise_(); w.activateWindow(); pump(0.6)                     # our app is in front, like after a click
mine = {}
def hook(pres, slide, added):
    mine["name"] = pres.Name
r = send(Picture(np.full((300, 400, 3), 120, np.uint8)), new_presentation=True, hook=hook, timeout=60)
hwnd = int(r.detail.get("hwnd") or 0)
w.raise_(); w.activateWindow(); pump(0.3)                     # make sure PowerPoint is behind us first
ok = bring_to_front(hwnd); pump(0.5)
fg = int(u32.GetForegroundWindow() or 0)
buf = ctypes.create_unicode_buffer(300); u32.GetWindowTextW(fg, buf, 300)
u32.ShowWindow(hwnd, 6); pump(0.5)                            # minimize PowerPoint
w.raise_(); w.activateWindow(); pump(0.3)
ok2 = bring_to_front(hwnd); pump(0.5)
restored = int(u32.GetForegroundWindow() or 0) == hwnd and not u32.IsIconic(hwnd)
import pythoncom, win32com.client
pythoncom.CoInitialize()
pp = win32com.client.GetActiveObject("PowerPoint.Application")
sel = None
for p in pp.Presentations:
    if p.Name == mine.get("name"):
        try:
            sel = int(p.Windows(1).Selection.Type)
        except Exception as e:
            sel = repr(e)
        p.Saved = True
        p.Close()
print("RESULT ok", ok, "front_is_ppt", fg == hwnd, "minimized_restored", ok2 and restored, "title", repr(buf.value), "selection", sel)
w.close()
'''


def _ok(out: str) -> bool:
    return "SKIP" in out or ("ok True front_is_ppt True minimized_restored True" in out and "selection 2" in out)


def test_PPT_FRONT_REAL_01_powerpoint_in_front_with_the_new_picture_selected(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(FLOW % ROOT, _ok)
    if "SKIP" in out:
        pytest.skip("PowerPoint not installed")
    assert _ok(out), out
