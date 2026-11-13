"""Screen recording core: frame timing at the chosen rate, pause, the length limit, dropped frames,
microphone + computer sound mixed onto the video's timeline. Fake clock, screen and writer."""
import wave

import numpy as np
import pytest

from capture_tool.core.geometry import Rect
from capture_tool.core.recording import AUDIO_LAG, RATE, RecordOptions, RecordingSession

R = Rect(10, 20, 64, 48)


class FakeWriter:
    def __init__(self):
        self.frames, self.audio, self.closed = [], [], False

    def add_frame(self, bgra, t):
        assert bgra.shape == (R.h, R.w, 4)
        self.frames.append(t)

    def add_audio(self, pcm, t):
        assert pcm.dtype == np.float32 and pcm.ndim == 2 and pcm.shape[1] == 2
        self.audio.append((t, pcm.copy()))

    def close(self):
        self.closed = True

    def samples(self):
        return np.concatenate([p for _, p in self.audio]) if self.audio else np.zeros((0, 2), np.float32)


def grab(r):
    return np.zeros((r.h, r.w, 4), np.uint8)


def session(tmp_path, fps=10, max_seconds=600, sources=(), writer=None, grab_fn=grab):
    w = writer or FakeWriter()
    s = RecordingSession(grab_fn, lambda **kw: w, R, RecordOptions(fps=fps, max_seconds=max_seconds),
                         path=tmp_path / "rec.mp4", sources=sources)
    return s, w


def test_REC_01_frames_come_at_the_chosen_rate(tmp_path):
    s, w = session(tmp_path, fps=10)
    s.begin(now=100.0)
    for i in range(101):                                 # every 10 ms for one second
        s.tick(100.0 + i * 0.01)
    s.finish(101.0)
    assert len(w.frames) == 11 and w.frames[0] == 0.0
    assert all(abs((b - a) - 0.1) < 0.011 for a, b in zip(w.frames, w.frames[1:]))
    assert w.closed and s.state == "done" and s.dropped == 0


def test_REC_02_a_pause_leaves_no_gap_in_the_video(tmp_path):
    s, w = session(tmp_path, fps=10)
    s.begin(now=0.0)
    for i in range(51):
        s.tick(i * 0.01)
    s.pause(0.5)
    for i in range(100):                                 # one second paused: nothing recorded
        s.tick(0.5 + i * 0.01)
    s.resume(1.5)
    for i in range(51):
        s.tick(1.5 + i * 0.01)
    s.finish(2.0)
    assert all(t <= 1.0 + 1e-9 for t in w.frames)       # the paused second is not in the video
    assert 10 <= len(w.frames) <= 12 and s.elapsed == pytest.approx(1.0, abs=0.02)


def test_REC_03_the_length_limit_ends_the_recording(tmp_path):
    s, w = session(tmp_path, fps=10, max_seconds=2)
    s.begin(now=0.0)
    t = 0.0
    while s.state == "recording" and t < 5:
        s.tick(t)
        t += 0.05
    assert s.state == "done" and s.reason == "limit" and w.closed
    assert max(w.frames) <= 2.0 + 1e-9


def test_REC_04_a_slow_moment_counts_as_dropped_frames(tmp_path):
    s, w = session(tmp_path, fps=10)
    s.begin(now=0.0)
    s.tick(0.0)
    s.tick(0.35)                                         # 0.1, 0.2 and 0.3 were missed
    s.finish(0.4)
    assert s.dropped == 2 and w.frames[-1] == pytest.approx(0.35)


class Source:
    def __init__(self, name):
        self.name = name


def test_REC_05_mic_and_computer_sound_are_mixed_onto_the_video_timeline(tmp_path):
    mic, system = Source("mic"), Source("system")
    s, w = session(tmp_path, sources=(mic, system))
    s.begin(now=0.0)
    s.feed(mic, np.full((RATE, 2), 0.5, np.float32), RATE)            # one second of mic
    s.feed(system, np.full((RATE // 2, 2), 0.25, np.float32), RATE)   # half a second, then silence
    s.tick(1.0)
    s.finish(1.0)
    out = w.samples()
    assert len(out) == RATE                                             # exactly the timeline: 1 s
    assert np.allclose(out[:RATE // 2], 0.75) and np.allclose(out[RATE // 2:], 0.5)


def test_REC_06_loud_mixes_are_clipped_and_audio_lags_behind_until_the_end(tmp_path):
    mic, system = Source("mic"), Source("system")
    s, w = session(tmp_path, sources=(mic, system))
    s.begin(now=0.0)
    s.feed(mic, np.full((RATE, 2), 0.8, np.float32), RATE)
    s.feed(system, np.full((RATE, 2), 0.8, np.float32), RATE)
    s.tick(1.0)
    assert len(w.samples()) == pytest.approx(RATE * (1.0 - AUDIO_LAG), abs=RATE // 100)   # late blocks may come
    s.finish(1.0)
    out = w.samples()
    assert len(out) == RATE and out.max() <= 1.0 and np.allclose(out, 1.0)


def test_REC_07_mono_or_44100_hz_blocks_become_48000_hz_stereo(tmp_path):
    mic = Source("mic")
    s, w = session(tmp_path, sources=(mic,))
    s.begin(now=0.0)
    s.feed(mic, np.full((44100, 1), 0.3, np.float32), 44100)
    s.finish(1.0)
    out = w.samples()
    assert out.shape == (RATE, 2) and np.allclose(out, 0.3, atol=1e-3)


def test_REC_08_the_sound_is_also_kept_as_a_wav_for_trimming(tmp_path):
    mic = Source("mic")
    s, w = session(tmp_path, sources=(mic,))
    s.begin(now=0.0)
    s.feed(mic, np.full((RATE, 2), 0.5, np.float32), RATE)
    s.finish(1.0)
    with wave.open(str(s.wav_path)) as wf:
        assert wf.getframerate() == RATE and wf.getnchannels() == 2 and wf.getnframes() == RATE


def test_REC_09_a_writer_error_ends_the_recording_and_says_why(tmp_path):
    class Broken(FakeWriter):
        def add_frame(self, bgra, t):
            raise OSError("disk full")
    s, w = session(tmp_path, writer=Broken())
    s.begin(now=0.0)
    s.tick(0.0)
    assert s.state == "failed" and "disk full" in s.error and w.closed


def test_REC_10_no_sound_sources_means_no_audio_track(tmp_path):
    s, w = session(tmp_path)
    s.begin(now=0.0)
    s.tick(0.5)
    s.finish(0.5)
    assert w.audio == [] and s.wav_path is None


def test_REC_11_the_recording_loop_runs_until_asked_to_stop(tmp_path):
    s, w = session(tmp_path, fps=10)
    clock = {"t": 0.0}

    def sleep(dt):
        assert 0 < dt <= 0.02                              # short waits: stopping is quick
        clock["t"] += dt
    s.begin(now=0.0)
    s.run(should_stop=lambda: clock["t"] >= 1.0, clock=lambda: clock["t"], sleep=sleep)
    assert s.state == "done" and s.reason == "stopped" and 10 <= len(w.frames) <= 11


def test_REC_12_a_frame_the_encoder_refuses_counts_as_dropped(tmp_path):
    class Busy(FakeWriter):
        def add_frame(self, bgra, t):
            super().add_frame(bgra, t)
            return len(self.frames) % 2 == 1                  # every other frame: still encoding
    s, w = session(tmp_path, fps=10, writer=Busy())
    s.begin(now=0.0)
    for i in range(10):
        s.tick(i * 0.1)
    s.finish(1.0)
    assert s.frames == 5 and s.dropped == 5


# --- the mouse in the video ----------------------------------------------------------------------
def _gray(w=200, h=120, ch=3):
    return np.full((h, w, ch), 128, np.uint8)


def test_REC_13_frames_become_bgra_whatever_the_grab_gives():
    from capture_tool.core.recording import to_bgra
    a = to_bgra(_gray(ch=3))
    assert a.shape == (120, 200, 4) and (a[..., 3] == 255).all() and (a[..., :3] == 128).all()
    b = to_bgra(_gray(ch=4))
    assert b.shape == (120, 200, 4)


def test_REC_14_the_pointer_is_drawn_where_the_mouse_is_inside_the_area():
    from capture_tool.core.recording import MousePainter
    rect = Rect(1000, 500, 200, 120)
    p = MousePainter(lambda: (1050, 560, False), cursor=True, clicks=True, clock=lambda: 0.0)
    img = p(_gray(), rect)
    assert img.shape == (120, 200, 4)
    assert (img[60:75, 50:56, :3] != 128).any()                        # the arrow hangs from its tip
    assert (img[0:30, 120:200, :3] == 128).all()                         # nothing elsewhere
    outside = MousePainter(lambda: (10, 10, False), cursor=True, clicks=True, clock=lambda: 0.0)
    assert (outside(_gray(), rect)[..., :3] == 128).all()


def test_REC_15_a_click_leaves_a_ring_for_half_a_second():
    from capture_tool.core.recording import MousePainter
    rect = Rect(0, 0, 200, 120)
    t = {"now": 0.0, "down": False}
    p = MousePainter(lambda: (100, 60, t["down"]), cursor=False, clicks=True, clock=lambda: t["now"])
    assert (p(_gray(), rect)[..., :3] == 128).all()                     # no click yet: nothing
    t["down"] = True
    p(_gray(), rect)                                                     # the button went down at 0.0
    t["down"], t["now"] = False, 0.2
    ring = p(_gray(), rect)
    assert (ring[..., :3] != 128).any() and (ring[60, 100, :3] == 128).all()     # a ring, its middle open
    t["now"] = 0.8
    assert (p(_gray(), rect)[..., :3] == 128).all()                     # gone after the half second


def test_REC_16_without_pointer_or_clicks_the_frame_is_untouched():
    from capture_tool.core.recording import MousePainter
    p = MousePainter(lambda: (50, 50, True), cursor=False, clicks=False, clock=lambda: 0.0)
    assert (p(_gray(), Rect(0, 0, 200, 120))[..., :3] == 128).all()


def test_REC_17_a_retina_pointer_is_drawn_bigger():
    from capture_tool.core.recording import MousePainter
    rect = Rect(0, 0, 200, 120)
    small = MousePainter(lambda: (20, 20, False), clock=lambda: 0.0)(_gray(), rect)
    big = MousePainter(lambda: (20, 20, False), clock=lambda: 0.0, scale=2.0)(_gray(), rect)
    assert (big[..., :3] != 128).sum() > 2 * (small[..., :3] != 128).sum()


def test_REC_18_a_muted_microphone_records_silence_while_the_computer_sound_goes_on(tmp_path):
    mic, system = Source("mic"), Source("system")
    s, w = session(tmp_path, sources=(mic, system))
    s.begin(now=0.0)
    s.mute("mic", True)
    s.feed(mic, np.full((RATE, 2), 0.5, np.float32), RATE)
    s.feed(system, np.full((RATE, 2), 0.25, np.float32), RATE)
    s.mute("mic", False)
    s.feed(mic, np.full((RATE, 2), 0.5, np.float32), RATE)          # back on: heard in the next second
    s.feed(system, np.full((RATE, 2), 0.25, np.float32), RATE)
    s.finish(2.0)
    out = w.samples()
    assert len(out) == 2 * RATE and np.allclose(out[:RATE], 0.25) and np.allclose(out[RATE:], 0.75)


# --- sound devices whose clocks are a little off (found by tools/long_recording_check.py) -----------
class DriftSource:
    """0.1 s blocks of `signal(wall seconds)` at RATE x (1 + ppm), each delivered 0-150 ms late."""

    def __init__(self, name, signal, ppm, seed):
        self.name, self.signal, self.ppm = name, signal, ppm
        self.rng = np.random.default_rng(seed)
        self.made, self.pending = 0, []

    def due(self, wall):
        rate = RATE * (1 + self.ppm * 1e-6)
        while (self.made + 4800) / rate <= wall:
            t0 = self.made / rate
            due = t0 + 4800 / rate + self.rng.uniform(0, 0.15)
            due = max(due, self.pending[-1][0]) if self.pending else due      # a stream keeps its order
            self.pending.append((due, self.signal(t0 + np.arange(4800) / rate)))
            self.made += 4800
        out = [b for d, b in self.pending if d <= wall]
        self.pending = [(d, b) for d, b in self.pending if d > wall]
        return out


def _beep(walls):
    on = (walls % 10.0 < 0.05) & (walls > 5)
    s = (0.5 * np.sin(2 * np.pi * 1000 * walls) * on).astype(np.float32)
    return np.stack([s, s], axis=1)


def _tone(walls):
    s = (0.1 * np.sin(2 * np.pi * 220 * walls)).astype(np.float32)
    return np.stack([s, s], axis=1)


def _power(x, hz, win):
    n = len(x) // win
    seg = x[:n * win].reshape(n, win)
    t = np.arange(win) / RATE
    return ((seg @ np.cos(2 * np.pi * hz * t)) ** 2 + (seg @ np.sin(2 * np.pi * hz * t)) ** 2) / win ** 2


def _drift_run(tmp_path, ppm_mic, ppm_sys, seconds):
    mic, system = DriftSource("mic", _beep, ppm_mic, 1), DriftSource("system", _tone, ppm_sys, 2)
    s, w = session(tmp_path, fps=5, max_seconds=seconds + 10, sources=(mic, system))
    s.begin(now=0.0)
    for i in range(1, int(seconds * 20) + 1):            # 50 ms ticks
        now = i * 0.05
        for src in (mic, system):
            for block in src.due(now):
                s.feed(src, block, RATE)
        s.tick(now)
    s.finish(seconds)
    x = w.samples()[:, 0]
    p = _power(x, 1000, 480)
    on = p > 0.01
    beeps = [i * 0.01 for i in np.flatnonzero(on & ~np.concatenate([[False], on[:-1]]))]
    gaps = [round(i * 0.1, 1) for i in np.flatnonzero(_power(x, 220, 4800) < 0.0005)]
    return beeps, gaps


def test_REC_19_a_fast_microphone_clock_does_not_pull_the_sound_behind_the_picture(tmp_path):
    """+0.2 % (a cheap USB microphone; 60 ppm is common): without correction the beeps came 0.36 s
    late after 3 minutes (0.47 s after 2 hours at 60 ppm in the long check)."""
    beeps, _ = _drift_run(tmp_path, ppm_mic=2000, ppm_sys=0, seconds=180)
    late = [b - round(b / 10) * 10 for b in beeps if b > 60]
    assert len(beeps) >= 16 and max(abs(d) for d in late) < 0.06, late


def test_REC_20_a_slow_device_clock_leaves_no_holes_in_the_sound(tmp_path):
    """-0.2 %: the device delivers a little less than the timeline uses; padding with silence made
    100 ms holes (23 in the 2-hour check at -60 ppm)."""
    beeps, gaps = _drift_run(tmp_path, ppm_mic=-2000, ppm_sys=-2000, seconds=180)
    late = [b - round(b / 10) * 10 for b in beeps if b > 60]
    assert [g for g in gaps if 1.0 < g < 179.0] == [] and max(abs(d) for d in late) < 0.06, (gaps, late)
