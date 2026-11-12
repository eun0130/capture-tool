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
