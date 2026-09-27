"""Real desktop: the frozen overlay must show every monitor at 1:1 (not shrunk or shifted)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import sys, time, tempfile, numpy as np
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen
from capture_tool.core.settings import Settings
from capture_tool.platform import screen
from tests.test_app import FakeClipboard, FakeOcr
tmp = tempfile.mkdtemp(dir=r"%s")
rs = RealScreen()
for m in rs.monitors():
    c = Controller(rs, FakeClipboard(), FakeOcr(), Settings(), tmp + "/s.json", tmp, sync=True)
    orig = rs.cursor_pos
    rs.cursor_pos = lambda m=m: (m.rect.x + 5, m.rect.y + 5)
    c.start_capture()
    rs.cursor_pos = orig
    for _ in range(15):
        app.processEvents(); time.sleep(0.02)
    ov = next(o for o in c.overlays if o.monitor.name == m.name)
    shown = screen.grab(m.rect)[:, :, :3].astype(np.float32)
    a = 140 / 255.0
    expected = ov.image[:, :, :3].astype(np.float32) * (1 - a) + np.array([24, 18, 15], np.float32) * a
    band = (slice(80, m.rect.h - 80), slice(0, m.rect.w))  # skip the hint bar and the taskbar
    d = np.abs(shown - expected).mean(axis=2)
    ys, xs = np.nonzero(d[band] > 40)
    where = f" big={len(ys)} x={xs.min()}..{xs.max()} y={ys.min() + 80}..{ys.max() + 80}" if len(ys) else ""
    print(f"{m.name} diff={float(d[band].mean()):.2f}{where}")
    c.close_all()
    app.processEvents()
'''


def _good(out: str) -> bool:
    lines = [l for l in out.splitlines() if "diff=" in l]
    return bool(lines) and all(float(l.split("diff=")[1].split()[0]) < 3.0 for l in lines)


def test_OVL_REAL_01_overlay_is_one_to_one_on_every_monitor(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(SCRIPT % (ROOT, tmp_path), _good)
    assert _good(out), out


POPUP_SCRIPT = r"""
import sys, time, tempfile
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen
from capture_tool.core.settings import Settings
from tests.test_app import FakeClipboard, FakeOcr, drag
def pump(n=10):
    for _ in range(n):
        app.processEvents(); time.sleep(0.02)
tmp = tempfile.mkdtemp(dir=r"%s")
c = Controller(RealScreen(), FakeClipboard(), FakeOcr(), Settings(), tmp + "/s.json", tmp, sync=True)
c.start_capture(); pump()
ov = c.active_overlay or c.overlays[0]
ov.activateWindow(); pump()
drag(ov, (200, 200), (700, 500)); pump()
ov.set_tool("text")
QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(260, 260)); pump()
ed = ov._editor
ed.insert("A")
tb = ov.toolbar
tb.open_symbols(); pump()
btn = next(b for b in tb.symbols.findChildren(QToolButton) if b.text() == "★")
QTest.mouseClick(btn, Qt.LeftButton); pump()
print("after_symbol", ov._editor is ed, repr(ed.text()) if ov._editor is ed else None)
tb.open_bg_palette(); pump()
sw = next(b for b in tb.bg_palette.findChildren(QPushButton) if b.toolTip() == "#FFEC99")
QTest.mouseClick(sw, Qt.LeftButton); pump()
print("after_bg", ov._editor is ed, tb.bg)
QTest.keyClick(ed, Qt.Key_Return); pump()
s = c.session.document.shapes[-1]
print("shape", repr(s.text), s.bg)
c.close_all(); pump()
"""


def _popup_ok(out: str) -> bool:
    return ("after_symbol True 'A★'" in out and "after_bg True #FFEC99" in out
            and "shape 'A★' #FFEC99" in out)


def test_OVL_REAL_02_symbol_and_background_popups_keep_the_text_box_open(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(POPUP_SCRIPT % (ROOT, tmp_path), _popup_ok)
    assert _popup_ok(out), out
