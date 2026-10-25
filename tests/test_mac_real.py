"""The real macOS APIs (run on a Mac only - `mac` marker): pasteboard round trip, window list and
window capture, Carbon hot key, Keychain, permissions. Screen Recording must be granted to the
Python / terminal app running the tests; tests that need Accessibility skip without it."""
import os
import time

import numpy as np
import pytest

pytestmark = pytest.mark.mac


@pytest.fixture
def mac_env(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")


def _skip_if_locked():
    """A locked Mac (front app loginwindow) delivers no global hot keys - unlock it and run again."""
    from Quartz import CGSessionCopyCurrentDictionary
    if (CGSessionCopyCurrentDictionary() or {}).get("CGSSessionScreenIsLocked"):
        pytest.skip("the screen is locked - unlock the Mac and run again")


def _skip_if_display_asleep():
    """A sleeping display makes every grab ~1 s and black - wake it and run again."""
    from Quartz import CGDisplayIsAsleep, CGMainDisplayID
    if CGDisplayIsAsleep(CGMainDisplayID()):
        pytest.skip("the display is asleep - wake the screen and run again")


def test_MACR_01_pasteboard_round_trip(mac_env):
    from capture_tool.core.clipboard_payload import HTML, PNG, UNICODE, cf_html
    from capture_tool.platform.mac import clipboard
    clipboard.set_formats({PNG: b"\x89PNG\r\n\x1a\nfake", HTML: cf_html("<b>x</b>"), UNICODE: "안녕"})
    assert clipboard.get_format(PNG) == b"\x89PNG\r\n\x1a\nfake"
    assert clipboard.get_text() == "안녕"
    assert clipboard.get_format(HTML).decode() == "<b>x</b>"
    assert clipboard.get_format("CF_DIB") is None


def test_MACR_02_windows_and_window_capture(mac_env, qt_app):
    from PySide6.QtWidgets import QWidget
    from capture_tool.platform.mac import permissions, windows
    if not permissions.screen_recording():
        pytest.skip("Screen Recording not granted to the test runner")
    w = QWidget()
    w.setWindowTitle("CaptureTool test window")
    w.resize(300, 200)
    w.show()
    qt_app.processEvents()
    time.sleep(0.3)
    wins = windows.top_level_windows()
    mine = [x for x in wins if x.pid == os.getpid()]
    assert mine and mine[0].rect.w >= 300
    assert windows.window_at((mine[0].rect.x + 5, mine[0].rect.y + 5), wins).hwnd == mine[0].hwnd
    assert windows.top_level_windows(exclude_pid=os.getpid()) == [x for x in wins if x.pid != os.getpid()]
    img = windows.capture_window(mine[0].hwnd, mine[0].rect)
    assert isinstance(img, np.ndarray) and img.shape[1] >= 300 and img.shape[2] == 3
    assert windows.process_name(mine[0].hwnd)


def test_MACR_03_screen_grab_matches_the_asked_size(mac_env, qt_app):
    from capture_tool.core.geometry import Rect
    from capture_tool.platform.mac import permissions, screen
    if not permissions.screen_recording():
        pytest.skip("Screen Recording not granted")
    mons = screen.monitors()
    assert mons and any(m.primary for m in mons)
    r = Rect(mons[0].rect.x, mons[0].rect.y, 200, 100)
    img = screen.grab(r)
    assert img.shape == (100, 200, 3)
    x, y = screen.cursor_pos()
    assert isinstance(x, int) and isinstance(y, int)


HOTKEY_FLOW = r"""
import os, time
os.environ["CAPTURE_PLATFORM"] = "darwin"
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.core.hotkey import parse
from capture_tool.platform.mac import hotkey
from Quartz import (CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags, kCGEventFlagMaskCommand,
                    kCGEventFlagMaskShift, kCGHIDEventTap)
got = []
hotkey.set_dispatch(got.append)
print("REGISTERED", hotkey.register(0, 0xA009, parse("Shift+Cmd+9")))
try:
    for down in (True, False):
        ev = CGEventCreateKeyboardEvent(None, 0x19, down)                       # kVK_ANSI_9
        CGEventSetFlags(ev, kCGEventFlagMaskCommand | kCGEventFlagMaskShift)
        CGEventPost(kCGHIDEventTap, ev)
    t0 = time.time()
    while not got and time.time() - t0 < 2:
        app.processEvents()
        time.sleep(0.02)
    print("GOT", got)
finally:
    hotkey.unregister(0, 0xA009)
print("REFUSED", not hotkey.register(0, 0xA00A, parse("Alt+PrintScreen")))   # no such key: refused, no crash
"""


def test_MACR_04_carbon_hotkey_fires(mac_env):
    """Carbon delivers hot keys through the Cocoa event loop, which offscreen Qt (this test session)
    never runs - so the check runs in a child process on the real desktop (cocoa platform)."""
    from tests.conftest import run_on_desktop
    _skip_if_locked()
    out = run_on_desktop(HOTKEY_FLOW, lambda o: "GOT [40969]" in o)
    assert "REGISTERED True" in out, out
    assert "GOT [40969]" in out, out                                             # 0xA009
    assert "REFUSED True" in out, out


def test_MACR_05_keychain_round_trip(mac_env):
    from capture_tool.platform.mac import secret
    blob = secret.protect("s3cret-value")
    try:
        assert blob.startswith("key-") and secret.unprotect(blob) == "s3cret-value"
    finally:
        secret.forget(blob)
    with pytest.raises(secret.SecretError):
        secret.unprotect(blob)


def test_MACR_06_permissions_report_booleans_and_open_the_pane(mac_env):
    from capture_tool.platform.mac import permissions
    assert isinstance(permissions.screen_recording(), bool) and isinstance(permissions.accessibility(), bool)
    ran = []
    permissions.open_settings("screen", runner=lambda cmd: ran.append(cmd))
    assert ran == [["open", permissions.PANES["screen"]]]


def test_MACR_07_shell_open_runs_open(mac_env, tmp_path):
    from capture_tool.platform.mac import shell
    ran = []
    shell.open_path(tmp_path, runner=lambda cmd: ran.append(cmd))
    shell.reveal(tmp_path / "a.png", runner=lambda cmd: ran.append(cmd))
    assert shell.open_url("mailto:a@b", runner=lambda cmd: ran.append(cmd)) and not shell.open_url("file:///x")
    assert ran == [["open", str(tmp_path)], ["open", "-R", str(tmp_path / "a.png")], ["open", "mailto:a@b"]]


GRAB_FLOW = r"""
import os, time
os.environ["CAPTURE_PLATFORM"] = "darwin"
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.platform.mac import screen
m = next(x for x in screen.monitors() if x.primary).rect
screen.grab(m)                                                                   # first call loads Quartz
best = 1e9
for _ in range(3):
    t0 = time.perf_counter()
    img = screen.grab(m)
    best = min(best, (time.perf_counter() - t0) * 1000)
print("SHAPE", img.shape == (m.h, m.w, 3), img.dtype, img.flags["C_CONTIGUOUS"], m)
print("MS %.0f" % best)
"""


@pytest.mark.timing
def test_MACR_08_a_full_screen_grab_is_fast(mac_env):
    """The overlay waits for this grab after the hot key: it stays well under 100 ms (measured
    10-20 ms on a 3420x2214 Retina screen, also while the screen is locked). A sleeping display
    makes every grab ~1 s and black - the test skips then. Real desktop (cocoa) child: offscreen Qt has a small fake screen."""
    import re
    from tests.conftest import run_on_desktop
    _skip_if_display_asleep()
    out = run_on_desktop(GRAB_FLOW, lambda o: "MS " in o and int(re.search(r"MS (\d+)", o).group(1)) < 100)
    assert "SHAPE True uint8 True" in out, out
    assert int(re.search(r"MS (\d+)", out).group(1)) < 100, out


def test_MACR_09_a_test_session_ends_without_a_segfault():
    """BUG-130: Qt windows left by the tests were freed at interpreter exit after QApplication was
    gone and the run ended in a segfault (139) on the Mac, which stopped build.sh. conftest closes them
    at session end; test_app.py alone used to reproduce it."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "--basetemp", str(root / ".pytest_tmp" / "macr09"), "tests/test_app.py"],
                       cwd=root, env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, (r.returncode, r.stdout[-800:], r.stderr[-800:])
