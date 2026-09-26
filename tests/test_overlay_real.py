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


def test_OVL_REAL_01_overlay_is_one_to_one_on_every_monitor(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    r = subprocess.run([sys.executable, "-c", SCRIPT % (ROOT, tmp_path)], cwd=ROOT, capture_output=True,
                       text=True, timeout=120, env=env)
    lines = [l for l in r.stdout.splitlines() if "diff=" in l]
    assert lines, r.stdout + r.stderr
    for l in lines:
        assert float(l.split("diff=")[1].split()[0]) < 3.0, l
