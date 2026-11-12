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


WINDOWS_FLOW = r"""
import os, time
os.environ["CAPTURE_PLATFORM"] = "darwin"
import numpy as np
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
from capture_tool.platform.mac import windows
w = QWidget()
w.setWindowTitle("CaptureTool test window")
w.resize(300, 200)
w.show()
for _ in range(15):
    app.processEvents(); time.sleep(0.02)
wins = windows.top_level_windows()
mine = [x for x in wins if x.pid == os.getpid()]
print("MINE", bool(mine) and mine[0].rect.w >= 300, mine[:1])
print("AT", windows.window_at((mine[0].rect.x + 5, mine[0].rect.y + 5), wins).hwnd == mine[0].hwnd)
print("EXCLUDE", windows.top_level_windows(exclude_pid=os.getpid()) == [x for x in wins if x.pid != os.getpid()])
img = windows.capture_window(mine[0].hwnd, mine[0].rect)
print("CAPTURE", isinstance(img, np.ndarray) and img.shape[1] >= 300 and img.shape[2] == 3, getattr(img, "shape", None))
print("NAME", bool(windows.process_name(mine[0].hwnd)))
"""


def test_MACR_02_windows_and_window_capture(mac_env):
    """Our own window in the Quartz window list, hit-testing and capturing it. Real desktop child:
    in the offscreen test session a QWidget is never a macOS window."""
    from capture_tool.platform.mac import permissions
    from tests.conftest import run_on_desktop
    if not permissions.screen_recording():
        pytest.skip("Screen Recording not granted to the test runner")
    _skip_if_display_asleep()
    out = run_on_desktop(WINDOWS_FLOW, lambda o: "NAME True" in o)
    for check in ("MINE True", "AT True", "EXCLUDE True", "CAPTURE True", "NAME True"):
        assert check in out, out


SCREEN_FLOW = r"""
import os
os.environ["CAPTURE_PLATFORM"] = "darwin"
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.core.geometry import Rect
from capture_tool.platform.mac import screen
mons = screen.monitors()
print("PRIMARY", bool(mons) and any(m.primary for m in mons), mons)
r = Rect(mons[0].rect.x, mons[0].rect.y, 200, 100)
print("SHAPE", screen.grab(r).shape == (100, 200, 3))
x, y = screen.cursor_pos()
print("CURSOR", isinstance(x, int) and isinstance(y, int))
"""


def test_MACR_03_screen_grab_matches_the_asked_size(mac_env):
    """Real monitors (Retina scale) and a small grab at the asked physical size. Real desktop child:
    offscreen Qt has a fake screen."""
    from capture_tool.platform.mac import permissions
    from tests.conftest import run_on_desktop
    if not permissions.screen_recording():
        pytest.skip("Screen Recording not granted")
    _skip_if_display_asleep()
    out = run_on_desktop(SCREEN_FLOW, lambda o: "CURSOR True" in o)
    for check in ("PRIMARY True", "SHAPE True", "CURSOR True"):
        assert check in out, out


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
from Quartz import kCGEventFlagMaskAlternate
from capture_tool.core.settings import default_hotkeys
default = default_hotkeys()["capture"]                                          # Option + ~ (Alt + ~ on Windows)
print("DEFAULT_REGISTERED", default, hotkey.register(0, 0xA00B, parse(default)))
try:
    for down in (True, False):
        ev = CGEventCreateKeyboardEvent(None, 0x32, down)                       # kVK_ANSI_Grave (the ~ key)
        CGEventSetFlags(ev, kCGEventFlagMaskAlternate)
        CGEventPost(kCGHIDEventTap, ev)
    t0 = time.time()
    while 0xA00B not in got and time.time() - t0 < 2:
        app.processEvents()
        time.sleep(0.02)
    print("DEFAULT_GOT", 0xA00B in got)
finally:
    hotkey.unregister(0, 0xA00B)
"""


def test_MACR_04_carbon_hotkey_fires(mac_env):
    """Carbon delivers hot keys through the Cocoa event loop, which offscreen Qt (this test session)
    never runs - so the check runs in a child process on the real desktop (cocoa platform)."""
    from tests.conftest import run_on_desktop
    _skip_if_locked()
    out = run_on_desktop(HOTKEY_FLOW, lambda o: "GOT [40969]" in o and "DEFAULT_GOT True" in o)
    assert "REGISTERED True" in out, out
    assert "GOT [40969]" in out, out                                             # 0xA009
    assert "REFUSED True" in out, out
    assert "DEFAULT_REGISTERED Option + ~ True" in out and "DEFAULT_GOT True" in out, out   # the default capture key


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


def _mp4_facts(path):
    """(frames decoded, frame shape, duration s, video tracks, audio tracks, audio float32 [n, 2])."""
    import cv2
    import AVFoundation as av
    import CoreAudio
    import CoreMedia
    from Foundation import NSURL
    cap = cv2.VideoCapture(str(path))
    frames, shape = 0, None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames, shape = frames + 1, f.shape
    asset = av.AVURLAsset.URLAssetWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
    v = asset.tracksWithMediaType_(av.AVMediaTypeVideo)
    a = asset.tracksWithMediaType_(av.AVMediaTypeAudio)
    pcm = np.zeros((0, 2), np.float32)
    if a:
        reader, _ = av.AVAssetReader.assetReaderWithAsset_error_(asset, None)
        out = av.AVAssetReaderTrackOutput.assetReaderTrackOutputWithTrack_outputSettings_(a[0], {
            av.AVFormatIDKey: CoreAudio.kAudioFormatLinearPCM, av.AVLinearPCMBitDepthKey: 32,
            av.AVLinearPCMIsFloatKey: True, av.AVLinearPCMIsNonInterleaved: False})
        reader.addOutput_(out)
        reader.startReading()
        chunks = []
        while (sb := out.copyNextSampleBuffer()) is not None:
            bb = CoreMedia.CMSampleBufferGetDataBuffer(sb)
            _, data = CoreMedia.CMBlockBufferCopyDataBytes(bb, 0, CoreMedia.CMBlockBufferGetDataLength(bb), None)
            chunks.append(np.frombuffer(bytes(data), np.float32))
        pcm = np.concatenate(chunks).reshape(-1, 2)
    return frames, shape, CoreMedia.CMTimeGetSeconds(asset.duration()), len(v), len(a), pcm


def test_MACR_10_a_recording_session_writes_an_mp4_with_picture_and_sound(tmp_path):
    """Screen recording on the Mac: the session (frame timing, sound mixing) into AVAssetWriter's
    H.264 + AAC - the encoder that comes with macOS. Read back: frames, length, both tracks, the tone."""
    from capture_tool.core.geometry import Rect
    from capture_tool.core.recording import RATE, RecordOptions, RecordingSession
    from capture_tool.platform.mac.recorder import open_writer
    r = Rect(0, 0, 321, 241)                                   # odd sizes: H.264 needs even ones
    n = {"i": 0}

    def grab(rect):
        img = np.zeros((rect.h, rect.w, 4), np.uint8)
        img[..., 3] = 255
        img[:, : 10 * n["i"] % rect.w, 2] = 255                # a red bar that grows
        n["i"] += 1
        return img
    mic = type("Mic", (), {})()
    s = RecordingSession(grab, open_writer, r, RecordOptions(fps=15), path=tmp_path / "rec.mp4", sources=(mic,))
    s.begin(now=0.0)
    tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(2 * RATE) / RATE)).astype(np.float32)
    s.feed(mic, np.stack([tone, tone], axis=1), RATE)
    import time
    for i in range(30):                                    # real time, like a recording: 1/15 s apart
        s.tick(i / 15)
        time.sleep(1 / 15)
    s.finish(2.0)
    assert s.state == "done", s.error
    frames, shape, dur, nv, na, pcm = _mp4_facts(tmp_path / "rec.mp4")
    assert frames == s.frames and s.frames + s.dropped == 30 and s.dropped <= 1 and shape == (240, 320, 3)
    assert abs(dur - 2.0) < 0.15 and nv == 1 and na == 1
    mid = pcm[len(pcm) // 4: 3 * len(pcm) // 4, 0]
    spec = np.abs(np.fft.rfft(mid))
    assert abs(np.fft.rfftfreq(len(mid), 1 / RATE)[spec.argmax()] - 440) < 5
    assert 0.18 < float(np.sqrt((mid ** 2).mean())) < 0.24                 # 0.3 / sqrt 2


def test_MACR_11_the_computers_sound_comes_through_screencapturekit():
    """Screen recording's computer sound on the Mac: 48 kHz stereo blocks keep coming (silence too)."""
    import time
    from capture_tool.platform.mac import audio, permissions
    if not permissions.screen_recording():
        pytest.skip("Screen Recording not granted")
    got = []
    src = audio.ScreenAudioSource()
    src.start(lambda block, rate: got.append((block.shape, rate)))
    time.sleep(1.5)
    src.stop()
    assert src.error is None, src.error
    frames = sum(s[0] for s, _ in got)
    assert got and all(r == 48000 and s[1] == 2 for s, r in got) and 48000 < frames < 96000


def test_MACR_12_the_microphone_comes_through_soundcard():
    import time
    from capture_tool.platform.mac import audio
    if audio.mic_permission() != "granted":
        pytest.skip("Microphone not granted to the test runner (no prompt from a test)")
    got = []
    src = audio.sources(mic=True, system=False)[0]
    src.start(lambda block, rate: got.append(block.shape))
    time.sleep(1.0)
    src.stop()
    assert src.error is None and got and all(s[1] == 2 for s in got)
