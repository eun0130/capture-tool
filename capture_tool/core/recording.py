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


def to_bgra(img: np.ndarray) -> np.ndarray:
    """The writers take BGRA; the Mac grab gives BGR."""
    if img.ndim == 3 and img.shape[2] == 4:
        return np.ascontiguousarray(img)
    out = np.empty(img.shape[:2] + (4,), np.uint8)
    out[..., :3] = img[..., :3]
    out[..., 3] = 255
    return out


# the arrow pointer, tip at (0, 0), in px at scale 1
_ARROW = np.array([(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)], np.float32)
RING_SECONDS = 0.5


class MousePainter:
    """Draws the mouse pointer and a ring where the left button went down onto each frame (screen
    grabs leave the pointer out). `mouse()` gives (x, y, left button down) in physical px; `scale` is
    the display's (2 on a Retina screen) so the pointer looks its real size."""

    def __init__(self, mouse: Callable[[], tuple[int, int, bool]], cursor: bool = True, clicks: bool = True,
                 clock: Callable[[], float] = time.monotonic, scale: float = 1.0):
        self.mouse, self.cursor, self.clicks, self.clock, self.scale = mouse, cursor, clicks, clock, scale
        self._down = False
        self._rings: list[tuple[float, int, int]] = []

    def __call__(self, img: np.ndarray, rect: Rect) -> np.ndarray:
        out = to_bgra(img)
        if not (self.cursor or self.clicks):
            return out
        try:
            x, y, down = self.mouse()
        except Exception:  # noqa: BLE001 - no pointer this frame rather than no frame
            return out
        now = self.clock()
        if self.clicks:
            if down and not self._down:
                self._rings.append((now, x, y))
            self._rings = [r for r in self._rings if now - r[0] < RING_SECONDS]
        self._down = bool(down)
        import cv2
        k = self.scale
        if self.clicks:
            for t0, rx, ry in self._rings:
                age = (now - t0) / RING_SECONDS
                radius = int(round((10 + 14 * age) * k))
                cv2.circle(out, (rx - rect.x, ry - rect.y), radius, (0, 200, 255, 255), max(2, int(3 * k)),
                           cv2.LINE_AA)
        lx, ly = x - rect.x, y - rect.y
        if self.cursor and -30 * k < lx < rect.w and -30 * k < ly < rect.h:
            pts = np.round(_ARROW * k + (lx, ly)).astype(np.int32)
            cv2.fillPoly(out, [pts], (255, 255, 255, 255), cv2.LINE_AA)
            cv2.polylines(out, [pts], True, (0, 0, 0, 255), max(1, int(round(k))), cv2.LINE_AA)
        return out


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
        self.muted: set[str] = set()       # source names silenced for now (the bar's 마이크 button)

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
                taken = self.writer.add_frame(np.ascontiguousarray(frame), t)
            except Exception as e:  # noqa: BLE001 - any writer / grab failure ends the recording
                self._fail(e)
                return
            if taken is False:                            # the encoder is still busy: this one is lost
                self.dropped += 1
            else:
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
    def mute(self, name: str, on: bool) -> None:
        with self._lock:
            (self.muted.add if on else self.muted.discard)(name)

    def feed(self, source, block: np.ndarray, samplerate: int) -> None:
        """A block from a sound source (any thread). Dropped while paused or not recording; while
        muted it is kept as silence of the same length, so the source's later sound stays in time."""
        with self._lock:
            if self.state != "recording" or id(source) not in self._buf:
                return
            pcm = to_stereo_48k(block, samplerate)
            if getattr(source, "name", None) in self.muted:
                pcm = np.zeros_like(pcm)
            self._buf[id(source)] = np.concatenate([self._buf[id(source)], pcm])

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
