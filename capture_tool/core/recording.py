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
DRIFT_WINDOW = 8.0        # s: a device's smallest backlog over this long shows its clock's drift
DRIFT_FIX_S = 8.0         # s over which a backlog error is taken back (proportional)
DRIFT_I_S = 40.0          # s: the integral part's time, it takes the lasting drift over
DRIFT_MAX = 0.005         # at most 0.5 % faster / slower (not heard)


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


class _Drift:
    """Keeps one device in step with the video. Its sound is placed by sample count, so a clock a
    little fast piles up (the sound slides behind the picture: 0.47 s after 2 h at 60 ppm) and a slow
    one runs dry (holes of silence). The smallest backlog over DRIFT_WINDOW is learned once and then
    held (PI control): the device's sound is consumed up to DRIFT_MAX faster or slower, resampled.
    A block that comes too late leaves silence where it belonged and is skipped by that much when it
    comes, so lateness never shifts the rest."""

    def __init__(self):
        self.ratio = 1.0                     # input samples taken per output sample
        self.carry = 0.0                     # the fraction of an input sample not taken yet
        self.owed = 0                        # input samples to skip (their place was filled with silence)
        self.first: float | None = None      # media time the device's sound began
        self.target: float | None = None     # learned backlog (samples)
        self.integral = 0.0
        self.last_t: float | None = None
        self.window: list[tuple[float, int]] = []

    def take(self, buf: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
        """n output samples from `buf` at the current ratio; (out, what is left of buf)."""
        if self.owed and len(buf):
            k = min(self.owed, len(buf))
            buf, self.owed = buf[k:], self.owed - k
        want = n * self.ratio + self.carry
        m = int(want)
        out = np.zeros((n, 2), np.float32)
        if len(buf) < m:                       # dry: what there is, in time, silence after it
            have = len(buf)
            k = min(n, int(have / self.ratio))
            if k:
                out[:k] = _stretch(buf, k)
            if self.first is not None:
                self.owed += m - have
            self.carry = 0.0
            return out, buf[have:]
        self.carry = want - m
        out[:] = _stretch(buf[:m], n)
        return out, buf[m:]

    def update(self, t: float, backlog: int, has_sound: bool) -> None:
        if self.first is None:
            if not has_sound:
                return
            self.first = t
        dt = 0.0 if self.last_t is None else max(0.0, t - self.last_t)
        self.last_t = t
        self.window.append((t, backlog - self.owed))
        while self.window and self.window[0][0] < t - DRIFT_WINDOW:
            self.window.pop(0)
        if t - self.first < DRIFT_WINDOW:
            return
        low = min(b for _, b in self.window)
        if self.target is None:
            self.target = low
            return
        err = (low - self.target) / RATE                     # s of sound piled up (+) or missing (-)
        self.integral = max(-DRIFT_MAX, min(DRIFT_MAX, self.integral + err * dt / (DRIFT_FIX_S * DRIFT_I_S)))
        self.ratio = 1.0 + max(-DRIFT_MAX, min(DRIFT_MAX, err / DRIFT_FIX_S + self.integral))


def _stretch(a: np.ndarray, n: int) -> np.ndarray:
    """`a` resampled to n samples (linear; the change is a fraction of a percent)."""
    if len(a) == n:
        return np.ascontiguousarray(a, np.float32)
    src = np.arange(len(a), dtype=np.float64)
    dst = np.linspace(0, len(a) - 1, n)
    return np.stack([np.interp(dst, src, a[:, c]) for c in range(2)], axis=1).astype(np.float32)


RING_BGR = (0, 200, 255)


def _pointer_template(k: float):
    pts = np.round(_ARROW * k + 2 * k + 2).astype(np.int32)
    size = (int(np.ceil(24 * k + 6)), int(np.ceil(16 * k + 6)))
    import cv2
    tmpl = np.full(size, 128, np.uint8)
    mask = np.zeros(size, np.uint8)
    cv2.fillPoly(tmpl, [pts], 255, cv2.LINE_AA)
    cv2.polylines(tmpl, [pts], True, 0, max(1, int(round(k))), cv2.LINE_AA)
    cv2.fillPoly(mask, [pts], 255)
    cv2.polylines(mask, [pts], True, 255, max(1, int(round(k))))
    return tmpl, mask


def erase_pointer(img: np.ndarray, scales=(1.0, 1.25, 1.5, 2.0, 2.5)) -> np.ndarray:
    """The app's own pointer arrow and click rings (MousePainter) painted over in a frame taken
    from a recording, so they don't turn into shapes or spoil a line of text. Returns `img`
    itself when there is nothing of ours in it."""
    import cv2
    bgr = img[:, :, :3]
    erase = np.zeros(bgr.shape[:2], np.uint8)
    b, g, r = (bgr[:, :, i].astype(np.int16) for i in range(3))
    yellow = ((b < 110) & (np.abs(g - RING_BGR[1]) < 55) & (r > 200)).astype(np.uint8)
    if yellow.any():
        n, labels, stats, _ = cv2.connectedComponentsWithStats(yellow)
        for j in range(1, n):
            x, y, w, h, area = stats[j]
            if 14 <= w <= 140 and 0.75 <= w / max(h, 1) <= 1.33 and area < 0.5 * w * h:   # a hollow ring
                erase[labels == j] = 255
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    for k in scales:
        tmpl, mask = _pointer_template(k)
        if gray.shape[0] < tmpl.shape[0] or gray.shape[1] < tmpl.shape[1]:
            continue
        res = cv2.matchTemplate(gray, tmpl, cv2.TM_SQDIFF, mask=mask)
        per_px = res / max(1, int((mask > 0).sum()))
        for y, x in zip(*np.where(per_px < 55 ** 2)):       # (sub-pixel placement at 1.5x: ~42)
            region = (mask > 0).astype(np.uint8) * 255
            erase[y:y + region.shape[0], x:x + region.shape[1]] |= region
    if not erase.any():
        return img
    erase = cv2.dilate(erase, np.ones((7, 7), np.uint8))          # with the video's soft edges
    out = img.copy()
    out[:, :, :3] = cv2.inpaint(np.ascontiguousarray(bgr), erase, 3, cv2.INPAINT_TELEA)
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
        self._drift = {id(s): _Drift() for s in self.sources}
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
                d = self._drift[key]
                out, rest = d.take(buf, n)
                mix += out
                self._buf[key] = rest
                d.update(upto, len(rest), len(buf) > 0)
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
