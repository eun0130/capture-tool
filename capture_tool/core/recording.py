"""Screen recording, the part every OS shares: grab the chosen area at the chosen rate and hand the
pictures to the OS's video writer, keep the timeline across pauses, stop at the length limit, count
the frames that came too late, and mix the microphone and the computer's sound onto the same
timeline (48 kHz stereo float32). The sound is also kept as a WAV, so a trimmed copy can be made
without decoding the MP4's audio.

Timing is driven from outside - `tick(now)` - so it runs the same in a recording thread and in tests."""
from __future__ import annotations

import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .geometry import Rect

RATE = 48000              # Hz, stereo float32 everywhere inside
AUDIO_LAG = 0.3           # s: sound is mixed this far behind the picture - devices deliver late


@dataclass
class RecordOptions:
    fps: int = 15
    max_seconds: int = 600


def to_stereo_48k(block: np.ndarray, samplerate: int) -> np.ndarray:
    """Any float block (mono or stereo, any rate) as 48 kHz stereo float32 (linear resampling)."""
    a = np.asarray(block, np.float32)
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[1] == 1:
        a = np.repeat(a, 2, axis=1)
    elif a.shape[1] > 2:
        a = a[:, :2]
    if samplerate != RATE and len(a):
        n = int(round(len(a) * RATE / samplerate))
        src = np.arange(len(a), dtype=np.float64)
        dst = np.linspace(0, len(a) - 1, n)
        a = np.stack([np.interp(dst, src, a[:, c]) for c in range(2)], axis=1).astype(np.float32)
    return np.ascontiguousarray(a)


class RecordingSession:
    """state: ready -> recording <-> paused -> done | failed. reason: end, limit, stopped."""

    def __init__(self, grab: Callable[[Rect], np.ndarray], open_writer: Callable, rect: Rect,
                 opts: RecordOptions, path, sources=()):
        self.grab, self.open_writer, self.rect, self.opts = grab, open_writer, rect, opts
        self.path = Path(path)
        self.sources = list(sources)
        self.wav_path = self.path.with_suffix(".wav") if self.sources else None
        self.state, self.reason, self.error = "ready", None, None
        self.frames = self.dropped = 0
        self.writer = None
        self._lock = threading.Lock()
        self._buf = {id(s): np.zeros((0, 2), np.float32) for s in self.sources}
        self._written = 0                 # audio samples written
        self._wav = None
        self._t0 = 0.0
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self._next = 0.0                  # media time of the next frame slot
        self._last_t = 0.0

    # --- time -------------------------------------------------------------------------------------
    def media_time(self, now: float) -> float:
        held = (now - self._paused_at) if self._paused_at is not None else 0.0
        return max(0.0, now - self._t0 - self._paused_total - held)

    @property
    def elapsed(self) -> float:
        return self._last_t

    # --- life cycle -------------------------------------------------------------------------------
    def begin(self, now: float) -> None:
        audio = {"rate": RATE, "channels": 2} if self.sources else None
        self.writer = self.open_writer(path=self.path, width=self.rect.w, height=self.rect.h, fps=self.opts.fps,
                                       audio=audio)
        if self.wav_path is not None:
            self._wav = wave.open(str(self.wav_path), "wb")
            self._wav.setnchannels(2)
            self._wav.setsampwidth(2)
            self._wav.setframerate(RATE)
        self._t0 = now
        self.state = "recording"

    def pause(self, now: float) -> None:
        with self._lock:
            if self.state == "recording":
                self._paused_at, self.state = now, "paused"

    def resume(self, now: float) -> None:
        with self._lock:
            if self.state == "paused":
                self._paused_total += now - self._paused_at
                self._paused_at, self.state = None, "recording"

    def tick(self, now: float) -> None:
        if self.state != "recording":
            return
        t = self.media_time(now)
        if t >= self.opts.max_seconds:
            self.finish(now, "limit")
            return
        if t + 1e-9 >= self._next:
            missed = int((t - self._next) * self.opts.fps + 1e-6)
            self.dropped += max(0, missed)
            try:
                frame = self.grab(self.rect)
                self.writer.add_frame(np.ascontiguousarray(frame), t)
            except Exception as e:  # noqa: BLE001 - any writer / grab failure ends the recording
                self._fail(e)
                return
            self.frames += 1
            self._next = (np.floor(t * self.opts.fps + 1e-9) + 1) / self.opts.fps
        self._last_t = max(self._last_t, t)
        self._pump(t - AUDIO_LAG)

    def finish(self, now: float, reason: str = "end") -> None:
        if self.state not in ("recording", "paused"):
            return
        if self.state == "paused":
            self.resume(now)
        self._last_t = max(self._last_t, min(self.media_time(now), float(self.opts.max_seconds)))
        try:
            self._pump(self._last_t)                    # the sound up to the picture's end
        except Exception as e:  # noqa: BLE001
            self._fail(e)
            return
        self._close()
        self.state, self.reason = "done", reason

    def _fail(self, e: Exception) -> None:
        self.error = str(e) or type(e).__name__
        self._close()
        self.state = "failed"

    def _close(self) -> None:
        for close in (getattr(self.writer, "close", None), getattr(self._wav, "close", None)):
            try:
                if close:
                    close()
            except Exception:  # noqa: BLE001 - closing what can be closed
                pass
        self._wav = None

    # --- sound ------------------------------------------------------------------------------------
    def feed(self, source, block: np.ndarray, samplerate: int) -> None:
        """A block from a sound source (any thread). Dropped while paused or not recording."""
        with self._lock:
            if self.state != "recording" or id(source) not in self._buf:
                return
            self._buf[id(source)] = np.concatenate([self._buf[id(source)], to_stereo_48k(block, samplerate)])

    def _pump(self, upto: float) -> None:
        """Write the mixed sound up to media time `upto`; a source with nothing yet adds silence."""
        if not self.sources:
            return
        with self._lock:
            n = int(round(max(0.0, upto) * RATE)) - self._written
            if n <= 0:
                return
            mix = np.zeros((n, 2), np.float32)
            for key, buf in self._buf.items():
                take = buf[:n]
                mix[:len(take)] += take
                self._buf[key] = buf[len(take):]
            np.clip(mix, -1.0, 1.0, out=mix)
            start = self._written / RATE
            self._written += n
        self.writer.add_audio(mix, start)
        if self._wav is not None:
            self._wav.writeframes((mix * 32767).astype("<i2").tobytes())

    # --- the recording thread -------------------------------------------------------------------
    def run(self, should_stop: Callable[[], bool], clock: Callable[[], float] = time.monotonic,
            sleep: Callable[[float], None] = time.sleep) -> None:
        """Tick until stopped, the limit is reached or the writer fails (call begin() first)."""
        while self.state in ("recording", "paused"):
            if should_stop():
                self.finish(clock(), "stopped")
                break
            now = clock()
            self.tick(now)
            wait = self._next - self.media_time(now) if self.state == "recording" else 0.02
            sleep(min(0.02, max(0.002, wait)))
