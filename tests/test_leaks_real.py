"""Real desktop: every feature repeated many times must not keep growing memory, GDI/USER objects,
handles or windows (tests/soak.py does the work in a separate process)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]


def test_LEAK_REAL_01_repeated_use_does_not_grow(tmp_path):
    import os
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "soak.py"), "20"], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=900)
    line = next((l for l in r.stdout.splitlines() if l.startswith("SOAK ")), None)
    assert line, r.stdout + r.stderr
    out = json.loads(line[5:])
    base, end = out["base"], out["end"]
    # 5 features x 20 rounds (copy+draw+text box, text mode+translate, pin, PPT, 6000 px editor)
    assert end["private_mb"] - base["private_mb"] < 80, out
    assert end["gdi"] - base["gdi"] <= 10, out
    assert end["user"] - base["user"] <= 10, out
    assert end["handles"] - base["handles"] <= 40, out
    assert end["top_widgets"] == base["top_widgets"], out
    assert end["py_threads"] <= base["py_threads"] + 1, out
