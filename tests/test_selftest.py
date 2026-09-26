"""End-to-end run on the real desktop: grab, select, draw, copy; checks speed targets."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]

ROOT = Path(__file__).resolve().parents[1]


def test_E2E_01_selftest_meets_speed_targets():
    r = subprocess.run([sys.executable, str(ROOT / "run_capture.py"), "--selftest"], cwd=ROOT,
                       capture_output=True, text=True, timeout=180)
    assert "SELFTEST OK" in r.stdout, r.stdout + r.stderr
