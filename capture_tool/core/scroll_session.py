"""Scroll capture driver: wheel the view down, let it settle, grab, join — until the page ends,
the user stops it, or a limit is reached.

`run()` is a generator that yields how long to wait (ms) before it continues, so the UI can
drive it with a timer and stay responsive (tests just iterate it)."""
from __future__ import annotations

from typing import Callable

import numpy as np

from .stitch import ADDED, FULL, NOMATCH, SAME, Stitcher

WAIT_AFTER_WHEEL = 150     # ms: only used while going to the top
POLL = 30                  # ms between grabs while waiting for the view to move and stop
NO_MOVE = 300              # ms without any change after a wheel: the view did not move
LAST_PROBE = 500           # ms: second "is this the end?" check (lazy-loading pages)
STABLE = 2                 # polls in a row without change = the (smooth) scroll has finished
WAIT_SETTLE = 60           # ms between grabs until two in a row are identical
SETTLE_TRIES = 6
WAIT_LAZY = 400            # ms: a page that loads more content at the bottom gets one more chance
MAX_NOTCHES = 25        # wheel notches in one step (step size comes from the measured px per notch)
STEP_FRACTION = 0.7        # scroll ~70% of the view per step: the rest overlaps for matching
TOP_TRIES = 60
LATE_TRIES = 3             # x WAIT_LAZY: a page viewer may draw newly revealed pages late
BLOCK_TRIES = 10           # x WAIT_LAZY: how long a blanked-out screen grab is waited out


def looks_blocked(frame: np.ndarray) -> bool:
    """Every pixel the same color: the screen grab was blanked (a security program or protected
    video blocking capture). Small areas are allowed to be plain."""
    h, w = frame.shape[:2]
    if h < 64 or w < 64:
        return False
    px = frame[..., :3] if frame.ndim == 3 else frame
    first = px[0, 0]
    if not (px[::7, ::7] == first).all():        # the usual case, decided on 1/49 of the pixels
        return False
    return bool((px == first).all())


class ScrollCapture:
    def __init__(self, grab: Callable[[], np.ndarray], wheel: Callable[[int], None], to_top: bool = False,
                 stop_requested: Callable[[], bool] = lambda: False, max_steps: int = 200,
                 max_height: int = 20000, max_pixels: int = 32_000_000,
                 progress: Callable[[int, int], None] | None = None,
                 still_visible: Callable[[], bool] = lambda: True):
        self.grab, self.wheel = grab, wheel
        self.to_top = to_top
        self.stop_requested = stop_requested
        self.max_steps = max_steps
        self.progress = progress
        self.still_visible = still_visible   # False once another window covers the area
        self.stitcher = Stitcher(max_height=max_height, max_pixels=max_pixels)
        self.reason: str | None = None     # end, noscroll, stopped, limit, full, nomatch
        self.steps = 0

    def _frame(self) -> np.ndarray:
        return np.ascontiguousarray(self.grab()[:, :, :3]).copy()

    def _settle(self):
        """Generator: grab until two grabs in a row are identical; the last grab is in self._f."""
        a = self._frame()
        for _ in range(SETTLE_TRIES):
            yield WAIT_SETTLE
            b = self._frame()
            if np.array_equal(a, b):
                break
            a = b
        self._f = a

    @staticmethod
    def _bottom_blank(frame: np.ndarray) -> bool:
        """The lower part (what scrolling revealed) has no detail while the upper part has."""
        import cv2
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detail = (g.max(axis=1).astype(int) - g.min(axis=1)) > 16
        h = len(detail)
        return detail[int(h * 0.65):].mean() < 0.03 and detail[:int(h * 0.65)].mean() > 0.1

    def _after_wheel(self, before: np.ndarray, no_move: int = NO_MOVE):
        """Generator: poll until the view has moved and stopped (or clearly didn't move), instead
        of a fixed wait. Sets self._f to the settled frame."""
        import time
        cur, nominal, moved, stable = before, 0, False, 0
        start = time.perf_counter()
        while True:
            yield POLL
            nominal += POLL
            # timers fire late (~50 ms for a 30 ms wait): count real time, not just the requests
            waited = max(nominal, (time.perf_counter() - start) * 1000)
            if waited >= 2000:
                break
            nxt = self._frame()
            if np.array_equal(nxt, cur):
                stable += 1
                if (moved and stable >= STABLE) or (not moved and waited >= no_move):
                    break
            else:
                moved = moved or not np.array_equal(nxt, before)
                stable = 0
            cur = nxt
        self._f = cur

    def _settle_drawn(self, before: np.ndarray | None = None, no_move: int = NO_MOVE):
        """Generator: settle, then give a viewer that draws pages late a moment to do so."""
        if before is None:
            yield from self._settle()
        else:
            yield from self._after_wheel(before, no_move)
            if np.array_equal(self._f, before):
                return                              # nothing moved: nothing new to wait for
        for _ in range(LATE_TRIES):
            if not self._bottom_blank(self._f):
                return
            before = self._f
            yield WAIT_LAZY
            yield from self._settle()
            if np.array_equal(before, self._f):
                return                          # really blank (an empty page)

    def _settle_unblocked(self, before: np.ndarray | None = None, no_move: int = NO_MOVE):
        """Generator: like _settle, but waits out a blanked grab; sets self._blocked if it stays."""
        yield from self._settle_drawn(before, no_move)
        self._blocked = False
        for _ in range(BLOCK_TRIES):
            if not looks_blocked(self._f):
                return
            yield WAIT_LAZY
            yield from self._settle_drawn()
        self._blocked = looks_blocked(self._f)

    def _report(self) -> None:
        if self.progress:
            self.progress(self.steps, self.stitcher.height)

    def run(self):
        if self.to_top:
            prev = self._frame()
            for _ in range(TOP_TRIES):
                if self.stop_requested():
                    break
                self.wheel(10)
                yield WAIT_AFTER_WHEEL
                cur = self._frame()
                if np.array_equal(prev, cur):
                    break
                prev = cur
        yield from self._settle_unblocked()
        if self._blocked:
            self.reason = "blocked"
            return
        first = self.stitcher.add(self._f)
        self._report()
        if first.status == FULL:
            self.reason = "full"
            return
        notches, expected, same, per_notch = 1, None, 0, 0.0
        while True:
            if self.stop_requested():
                self.reason = "stopped"
                return
            if self.steps >= self.max_steps:
                self.reason = "limit"
                return
            if not self.still_visible():
                self.reason = "covered"
                return
            before = self._f
            self.wheel(-notches)
            self.steps += 1
            # after one "didn't move", the last probe waits longer: pages that load more at the end
            yield from self._settle_unblocked(before, LAST_PROBE if same else NO_MOVE)
            if self._blocked:
                self.reason = "blocked"
                return
            r = self.stitcher.add(self._f, expected)
            if r.status == SAME:
                same += 1
                if same >= 2:
                    self.reason = "end" if self.stitcher.pieces else "noscroll"
                    return
                continue
            if r.status == NOMATCH:
                # the view may still have been moving (smooth scroll, page-end bounce, a late
                # repaint): look once more before giving up
                yield WAIT_LAZY
                yield from self._settle()
                r = self.stitcher.add(self._f, expected)
                if r.status == SAME:
                    same += 1
                    continue
                if r.status == NOMATCH:
                    self.reason = "nomatch"
                    return
            same = 0
            self._report()
            if r.status == FULL:
                self.reason = "full"
                return
            # adapt the step: about STEP_FRACTION of the scrolling band per step. The largest
            # px-per-notch seen is used: a short step at the page end must not make the next
            # step jump past the view
            per_notch = max(per_notch, r.shift / notches)
            per = per_notch
            h = self._f.shape[0]
            band = h - (self.stitcher.top or 0) - (self.stitcher.bottom or 0)
            notches = int(min(MAX_NOTCHES, max(1, (band * STEP_FRACTION) // max(per, 1))))
            expected = round(notches * per)

    def result(self) -> np.ndarray:
        return self.stitcher.result()
