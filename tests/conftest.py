import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 맥에서는 이 두 파일을 모듈 import 단계에서 Windows 모듈(winreg, WinDLL)을 불러 수집이 깨지므로 건너뛴다.
collect_ignore = [] if sys.platform == "win32" else ["test_platform_win.py", "test_office_real.py"]


@pytest.fixture(autouse=True)
def _windows_contract(request, monkeypatch):
    """Tests marked windows_contract assert Windows behaviour (labels, defaults, edition buttons)."""
    if request.node.get_closest_marker("windows_contract"):
        monkeypatch.setenv("CAPTURE_PLATFORM", "win32")


def run_on_desktop(code: str, ok, attempts: int = 3, timeout: int = 180) -> str:
    """Run a script on the real desktop (not offscreen). The person may be using the PC while
    tests run (notifications, other windows), so a measurement disturbed by that is retried.
    Returns the output of the first attempt that satisfies `ok(stdout)`, else the last one."""
    import subprocess
    import sys
    from pathlib import Path
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PYTHONIOENCODING"] = "utf-8"   # symbols (★) in the output must survive cp949 consoles
    out = ""
    for _ in range(attempts):
        r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
        out = r.stdout + r.stderr
        if ok(r.stdout):
            return r.stdout
    return out


def _windowless_excel() -> set[int]:
    """Process ids of Excel instances without a window (COM automation servers)."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq EXCEL.EXE", "/FI", "WINDOWTITLE eq N/A", "/FO", "CSV",
                              "/NH"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=10).stdout or ""       # console code page: only the ASCII rows matter
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()
    return {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"EXCEL.EXE"')}


def pytest_sessionstart(session):
    session.config._excel_before = _windowless_excel()


def pytest_sessionfinish(session, exitstatus):
    """BUG-125: an Excel a flow started and did not get rid of stays for hours and slows every
    clipboard change on the PC. Name them here so a leak is seen on the run that caused it."""
    new = _windowless_excel() - getattr(session.config, "_excel_before", set())
    if new:
        print(f"\nWARNING: {len(new)} windowless EXCEL.EXE appeared during this session (pids {sorted(new)}): "
              f"a test left Excel behind - see BUG-125")


@pytest.fixture(scope="session")
def qt_app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app = QApplication.instance() or QApplication([])
    # offscreen Qt sees no system fonts: register the default font so every test draws real text
    # regardless of which test ran first
    # 맥에는 맑은 고딕이 없다 - 같은 역할의 한글 시스템 폰트로 대신한다
    font = r"C:\Windows\Fonts\malgun.ttf" if sys.platform == "win32" else "/System/Library/Fonts/AppleSDGothicNeo.ttc"
    QFontDatabase.addApplicationFont(font)
    yield app


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch, request):
    """A modal dialog opened by mistake would wait forever under the test runner: fail at once.
    Tests that drive a dialog themselves don't call exec()."""
    if "real" in request.node.nodeid or "office" in request.node.nodeid:
        return
    from PySide6.QtWidgets import QDialog, QMessageBox

    def refuse(self, *a, **k):
        raise AssertionError(f"modal dialog opened in a test: {type(self).__name__} {self.windowTitle()!r}")
    monkeypatch.setattr(QDialog, "exec", refuse)
    monkeypatch.setattr(QMessageBox, "exec", refuse)


@pytest.fixture(autouse=True)
def _never_touch_the_users_office(monkeypatch, request):
    """Tests must never paste into the person's open Excel / Word / PowerPoint: the 'running app'
    lookups say "not open" unless a test is an explicit real-Office one (own instances)."""
    if "real" in request.node.nodeid or "office" in request.node.nodeid:
        return
    from capture_tool.platform import excel

    def not_open():
        raise excel.ExcelNotOpen("Excel이 열려 있지 않습니다.")

    def never_start():
        raise AssertionError("a test tried to start Excel")
    monkeypatch.setattr(excel, "_running_app", not_open)
    monkeypatch.setattr(excel, "_start_app", never_start)
    monkeypatch.setattr(excel, "installed", lambda: False)


def pytest_collection_modifyitems(config, items):
    """OS-bound tests: `mac` ones run only on a Mac, `windows` ones only on Windows."""
    import sys
    skip_mac = pytest.mark.skip(reason="needs macOS")
    skip_win = pytest.mark.skip(reason="needs Windows")
    for item in items:
        if "mac" in item.keywords and sys.platform != "darwin":
            item.add_marker(skip_mac)
        if "windows" in item.keywords and sys.platform == "darwin":
            item.add_marker(skip_win)
