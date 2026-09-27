import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run_on_desktop(code: str, ok, attempts: int = 3, timeout: int = 180) -> str:
    """Run a script on the real desktop (not offscreen). The person may be using the PC while
    tests run (notifications, other windows), so a measurement disturbed by that is retried.
    Returns the output of the first attempt that satisfies `ok(stdout)`, else the last one."""
    import subprocess
    import sys
    from pathlib import Path
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    out = ""
    for _ in range(attempts):
        r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                           capture_output=True, text=True, timeout=timeout, env=env)
        out = r.stdout + r.stderr
        if ok(r.stdout):
            return r.stdout
    return out


@pytest.fixture(scope="session")
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
