"""Real desktop (not offscreen): a pinned capture must sit exactly over the captured region
on every monitor, including mixed DPI (e.g. 150% + 100%)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import sys, numpy as np
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen
from capture_tool.core.geometry import Rect
from capture_tool.core.settings import Settings
from capture_tool.platform import screen
from tests.test_app import FakeClipboard, FakeOcr
import tempfile, time
tmp = tempfile.mkdtemp(dir=r"%s")
rs = RealScreen()
for m in rs.monitors():
    c = Controller(rs, FakeClipboard(), FakeOcr(), Settings(), tmp + "/s.json", tmp, sync=True)
    rs_cursor = rs.cursor_pos
    rs.cursor_pos = lambda m=m: (m.rect.x + 10, m.rect.y + 10)
    c.start_capture()
    rs.cursor_pos = rs_cursor
    ov = next(o for o in c.overlays if o.monitor.name == m.name)
    sel = Rect(m.rect.x + m.rect.w // 4, m.rect.y + m.rect.h // 4, m.rect.w // 3, m.rect.h // 3)
    c.on_select_rect(sel, ov)
    before = ov.crop(sel).astype(int)
    c.finish("pin")
    for _ in range(20):
        app.processEvents(); time.sleep(0.02)
    after = screen.grab(sel)[:, :, :3].astype(int)
    inner = np.abs(after[6:-6, 6:-6] - before[6:-6, 6:-6]).mean()
    print(f"{m.name} scale={m.scale} diff={inner:.2f}")
    c.close_all()
    app.processEvents()
'''


def test_PIN_REAL_01_pin_sits_exactly_over_capture(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    code = SCRIPT % (ROOT, tmp_path)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       timeout=120, env=env)
    lines = [l for l in r.stdout.splitlines() if "diff=" in l]
    assert lines, r.stdout + r.stderr
    for l in lines:
        assert float(l.split("diff=")[1]) < 3.0, l  # same pixels (only moving content could differ)
