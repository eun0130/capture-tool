"""Sound sources for screen recording: a device read in short blocks on its own thread (so stopping
is quick even when the computer's sound delivers nothing during silence), failures kept, not raised."""
import threading
import time

import numpy as np

from capture_tool.platform.sound_common import BLOCK, SoundcardSource


class FakeRecorder:
    def __init__(self, dev):
        self.dev = dev

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.dev.closed = True

    def record(self, numframes):
        time.sleep(0.005)
        self.dev.reads += 1
        return np.full((numframes, 2), 0.25, np.float32)


class FakeDevice:
    def __init__(self):
        self.reads, self.closed, self.kw = 0, False, None

    def recorder(self, **kw):
        self.kw = kw
        return FakeRecorder(self)


def test_SND_01_a_source_hands_over_48k_stereo_blocks_until_stopped():
    dev = FakeDevice()
    got = []
    src = SoundcardSource("mic", lambda: dev)
    src.start(lambda block, rate: got.append((block.shape, rate)))
    time.sleep(0.1)
    src.stop()
    n = len(got)
    time.sleep(0.05)
    assert n > 0 and len(got) == n and dev.closed                       # nothing after stop
    assert got[0] == ((BLOCK, 2), 48000) and dev.kw["samplerate"] == 48000 and dev.kw["channels"] == 2


def test_SND_02_a_device_that_fails_is_reported_not_raised():
    def missing():
        raise RuntimeError("no microphone")
    src = SoundcardSource("mic", missing)
    src.start(lambda block, rate: None)
    src.stop()
    assert "no microphone" in src.error


def test_SND_03_stop_does_not_wait_long_for_a_silent_device():
    blocked = threading.Event()

    class Silent(FakeRecorder):
        def record(self, numframes):
            blocked.wait(5)                                      # the computer's sound during silence
            return np.zeros((0, 2), np.float32)
    dev = FakeDevice()
    dev.recorder = lambda **kw: Silent(dev)
    src = SoundcardSource("system", lambda: dev)
    src.start(lambda block, rate: None)
    time.sleep(0.05)
    t = time.perf_counter()
    src.stop()
    assert time.perf_counter() - t < 1.5                         # gives up waiting, recording can end
    blocked.set()


def test_SND_04_screencapturekit_planar_float_blocks_become_frames_by_2():
    from capture_tool.platform.mac.audio import interleave
    left, right = np.arange(4, dtype=np.float32), np.arange(4, dtype=np.float32) + 10
    planar = np.concatenate([left, right]).tobytes()                  # all left samples, then all right
    assert interleave(planar, 4, 2, True).tolist() == [[0, 10], [1, 11], [2, 12], [3, 13]]
    packed = np.stack([left, right], axis=1).tobytes()
    assert interleave(packed, 4, 2, False).tolist() == [[0, 10], [1, 11], [2, 12], [3, 13]]
    assert interleave(left.tobytes(), 4, 1, True).tolist() == [[0, 0], [1, 1], [2, 2], [3, 3]]


def test_SND_05_soundcard_is_imported_on_a_fresh_thread_once():
    """soundcard initialises COM when it is imported and raises if the importing thread already has
    COM in the other mode's S_FALSE case (seen on the Windows runner: PWIN-36 recorded without sound).
    The import runs on a new thread with no COM yet; an import error comes back to the caller."""
    from capture_tool.platform import sound_common
    seen = []

    def importer():
        seen.append(threading.get_ident())
        return "module"
    sound_common._soundcard_module = None
    assert sound_common.import_soundcard(importer) == "module"
    assert sound_common.import_soundcard(importer) == "module" and len(seen) == 1     # kept
    assert seen[0] != threading.get_ident()
    sound_common._soundcard_module = None

    def broken():
        raise RuntimeError("Error 0x100000001")
    try:
        sound_common.import_soundcard(broken)
        raise AssertionError("no error")
    except RuntimeError as e:
        assert "0x100000001" in str(e)
    sound_common._soundcard_module = None
