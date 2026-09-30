"""Scroll capture: join overlapping screenshots of a scrolling view into one tall image.

Each new frame is compared with the previous one:
- rows that stay put at the top/bottom (sticky header/footer) are measured once and kept once;
- in the band between them, the content moved up by `shift` rows; the new rows at the bottom
  of the band are appended.
Rows are compared by exact hashes of their (slightly quantized) gray values, over the middle
columns only, so a scrollbar or a hover effect at the edge doesn't break the match. Plain rows
(white space) match anything and are ignored when scoring a shift."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

ADDED, SAME, NOMATCH, FULL = "added", "same", "nomatch", "full"
MIN_SCORE = 0.9          # share of informative overlap rows that must match exactly
MIN_INFO_ROWS = 8        # informative rows needed in the overlap to trust a shift
LOOSE_SCORE = 0.6        # partly covered view: the best shift must still match this much ...
LOOSE_MARGIN = 0.3       # ... and beat every shift farther than NEAR rows away by this much
NEAR = 16
ROW_TOL = 8              # gray levels: rows this close count as equal (anti-aliasing at 125%/150%)
TOL_STEP = 4             # every 4th column is enough for the tolerant comparison
STRIPS = 8               # vertical strips voting on the shift when only part of the view scrolls
CLASS_MARGIN = 0.15      # a column "moves" / "stays" when one comparison beats the other by this
GROW = 16                # blank columns kept beside the scrolling content when cropping a panel off
EDGE_ZONE = 40           # px at the right edge where a moving scrollbar is looked for
MAX_BAND_FRACTION = 1 / 3  # sticky header / footer can't be more than this of the frame each


@dataclass
class StepResult:
    status: str
    shift: int = 0


def _bgr(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(frame[:, :, :3])


class Stitcher:
    def __init__(self, max_height: int = 20000, max_pixels: int = 32_000_000):
        self.max_height = max_height
        self.max_pixels = max_pixels
        self.first: np.ndarray | None = None
        self.last: np.ndarray | None = None
        self.pieces: list[np.ndarray] = []
        self.top = self.bottom = None          # sticky header / footer rows (fixed at the first move)
        self.crop_right = 0
        self.truncated = False
        self.frames = 0
        self._weights = None
        self._prev_hash = self._prev_info = None
        self._moving = self._static = None       # per-column votes: scrolls with the content / stays put
        self.guessed = 0                          # steps joined on the expected shift (blank overlap)

    # --- row signatures --------------------------------------------------------------
    def _cols(self, w: int) -> slice:
        m = max(16, int(w * 0.03))
        return slice(m, max(m + 1, w - m))

    def _signature(self, img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[:, self._cols(img.shape[1])]
        q = (gray >> 2).astype(np.uint64)
        if self._weights is None or self._weights.shape[0] != q.shape[1]:
            rng = np.random.default_rng(12345)
            self._weights = rng.integers(1, 2 ** 62, q.shape[1], dtype=np.uint64)
        h = q @ self._weights                                  # wraps mod 2^64: a row hash
        info = (gray.max(axis=1).astype(int) - gray.min(axis=1)) > 16
        return h, info

    # --- joining --------------------------------------------------------------------
    @property
    def height(self) -> int:
        if self.first is None:
            return 0
        return self.first.shape[0] + sum(p.shape[0] for p in self.pieces)

    def _cap(self) -> int:
        w = self.first.shape[1] if self.first is not None else 1
        return max(1, min(self.max_height, self.max_pixels // max(1, w)))

    def add(self, frame: np.ndarray, expected: int | None = None) -> StepResult:
        img = _bgr(frame)
        self.frames += 1
        if self.first is None:
            self.first = self.last = img
            self._prev_hash, self._prev_info = self._signature(img)
            self._prev_gray = self._gray(img)
            if img.shape[0] > self._cap():
                self.truncated = True
                return StepResult(FULL)
            return StepResult(ADDED)
        if img.shape != self.last.shape:
            raise ValueError(f"frame size changed: {img.shape} vs {self.last.shape}")
        h = img.shape[0]
        ch, ci = self._signature(img)
        ph, pi = self._prev_hash, self._prev_info
        if np.array_equal(ch, ph):
            return StepResult(SAME)
        cg, pg = self._gray(img), self._prev_gray
        if self.top is None:
            self.top, self.bottom = self._sticky(ph == ch, h)
            if self.top == 0 and self.bottom == 0:      # maybe only anti-aliasing differs
                self.top, self.bottom = self._sticky(self._row_diff(pg, cg) < ROW_TOL, h)
        t, b = self.top, h - self.bottom
        shift = self._find_shift(ph[t:b], pi[t:b], ch[t:b], expected)
        if shift is None:
            # exact rows didn't line up: allow the small pixel differences that fractional
            # scroll positions cause on scaled displays
            shift = self._find_shift_tolerant(pg[t:b], cg[t:b], pi[t:b], expected)
        if shift is None:
            # only part of the width scrolls (PDF thumbnails, a fixed side menu, frozen columns):
            # let vertical strips vote; the ones that stay put are left out
            shift = self._strip_shift(self.last[t:b], img[t:b], expected)
        if (shift is None or shift == 0) and expected:
            left, right = self._column_span(img.shape[1])       # the part that scrolls
            moved = not np.array_equal(self.last[t:b, left:right], img[t:b, left:right])
            if moved and self._overlap_blank(self.last[t:b, left:right], expected):
                shift = expected      # nothing to line up (blank page / gap): trust the scroll step
                self.guessed += 1
        if shift is None:
            return StepResult(NOMATCH)
        if shift == 0:
            return StepResult(SAME)
        self._classify_columns(self.last[t:b], img[t:b], shift)
        self._note_scrollbar(self.last[t:b], img[t:b], shift)
        new = img[b - shift:b]
        room = self._cap() - self.height
        status = ADDED
        if new.shape[0] > room:
            new = new[:max(0, room)]
            self.truncated = True
            status = FULL
        if new.shape[0]:
            self.pieces.append(new)
        self.last = img
        self._prev_hash, self._prev_info = ch, ci
        self._prev_gray = cg
        return StepResult(status, shift)

    # --- partial-width scrolling ------------------------------------------------------------
    def _strip_shift(self, prev_band: np.ndarray, cur_band: np.ndarray, expected) -> int | None:
        pg = cv2.cvtColor(prev_band, cv2.COLOR_BGR2GRAY).astype(np.int16)
        cg = cv2.cvtColor(cur_band, cv2.COLOR_BGR2GRAY).astype(np.int16)
        n, w = pg.shape
        edges = np.linspace(0, w, STRIPS + 1).astype(int)
        rng = np.random.default_rng(777)
        weights = rng.integers(1, 2 ** 62, w, dtype=np.uint64)
        min_overlap = max(20, n // 20)
        votes: list[tuple[int, int]] = []
        still = 0
        for a0, a1 in zip(edges[:-1], edges[1:]):
            P, C = pg[:, a0:a1], cg[:, a0:a1]
            info = (P.max(axis=1) - P.min(axis=1)) > 16
            k_all = int(info.sum())
            if k_all < MIN_INFO_ROWS:
                continue
            ph = (P >> 2).astype(np.uint64) @ weights[a0:a1]
            ch = (C >> 2).astype(np.uint64) @ weights[a0:a1]
            scored, loose = [], []
            for dy in range(0, n - min_overlap + 1):
                m = info[dy:]
                k = int(m.sum())
                if k < MIN_INFO_ROWS:
                    continue
                scored.append((float((ph[dy:][m] == ch[:n - dy][m]).mean()), dy, k))
            dy = self._pick_strict(scored, expected)
            if dy is None:                                   # tolerant, every 4th column
                Ps, Cs = P[:, ::TOL_STEP], C[:, ::TOL_STEP]
                for d in range(0, n - min_overlap + 1):
                    m = info[d:]
                    k = int(m.sum())
                    if k >= MIN_INFO_ROWS:
                        close = np.abs(Ps[d:][m] - Cs[:n - d][m]).mean(axis=1) < ROW_TOL
                        loose.append((float(close.mean()), d, k))
                dy = self._pick_strict(loose, expected)
            if dy is None:
                continue
            if dy == 0:
                still += k_all
            else:
                votes.append((dy, k_all))
        if not votes:
            return 0 if still else None
        # only a shift at least two strips agree on counts (one strip alone could be a coincidence)
        groups = [[(d, wt) for d, wt in votes if abs(d - v[0]) <= 2] for v in votes]
        groups = [g for g in groups if len(g) >= 2]
        if not groups:
            return None
        group = max(groups, key=lambda g: sum(wt for _, wt in g))
        return max(group, key=lambda v: v[1])[0]

    @staticmethod
    def _pick_strict(scored, expected) -> int | None:
        """Like _pick, but only clear matches (a narrow strip has too little to go on loosely)."""
        best = [c for c in scored if c[0] >= MIN_SCORE]
        if not best:
            return None
        top_score = max(sc for sc, _, _ in best)
        tied = [(dy, k) for sc, dy, k in best if sc >= top_score - 0.01]
        if expected is not None:
            return min(tied, key=lambda t: (abs(t[0] - expected), t[0]))[0]
        return max(tied, key=lambda t: (t[1], -t[0]))[0]

    @staticmethod
    def _overlap_blank(prev_band: np.ndarray, expected: int) -> bool:
        """The rows that would overlap after `expected` hold no detail (blank page, page gap)."""
        g = cv2.cvtColor(prev_band[expected:], cv2.COLOR_BGR2GRAY).astype(np.int16)
        if g.shape[0] == 0:
            return False
        # every row (nearly) the same: nothing that could show how far it moved
        same_as_first = np.abs(g - g[0]).max(axis=1) <= 16
        return same_as_first.mean() >= 0.98

    def _classify_columns(self, prev_band: np.ndarray, cur_band: np.ndarray, shift: int) -> None:
        """Per column: does it follow the scroll, or stay where it was (a panel that doesn't scroll)?"""
        n = prev_band.shape[0]
        if n - shift <= 0:
            return
        pg = cv2.cvtColor(prev_band, cv2.COLOR_BGR2GRAY).astype(np.int16)
        cg = cv2.cvtColor(cur_band, cv2.COLOR_BGR2GRAY).astype(np.int16)
        moved = (np.abs(pg[shift:] - cg[:n - shift]) <= 12).mean(axis=0)
        stayed = (np.abs(pg[shift:] - cg[shift:]) <= 12).mean(axis=0)
        if self._moving is None:
            self._moving = np.zeros(pg.shape[1], np.int32)
            self._static = np.zeros(pg.shape[1], np.int32)
        self._moving += moved > stayed + CLASS_MARGIN
        self._static += stayed > moved + CLASS_MARGIN

    def _column_span(self, w: int) -> tuple[int, int]:
        """Columns of the scrolling part: from the first to the last column that moved, grown
        over neutral (blank) columns but never into ones that stayed put."""
        if self._moving is None or not (self._static > self._moving).any():
            return 0, w
        mv = self._moving > self._static
        st = self._static > self._moving
        cols = np.nonzero(mv)[0]
        if len(cols) == 0:
            return 0, w
        left, right = int(cols[0]), int(cols[-1]) + 1
        lo, hi = max(0, left - GROW), min(w, right + GROW)   # a little blank margin, not a whole panel
        while left > lo and not st[left - 1]:
            left -= 1
        while right < hi and not st[right]:
            right += 1
        return left, right

    def _gray(self, img: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[:, self._cols(img.shape[1])][:, ::TOL_STEP].astype(np.int16)

    @staticmethod
    def _row_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.abs(a - b).mean(axis=1)

    @staticmethod
    def _sticky(same, h) -> tuple[int, int]:
        limit = int(h * MAX_BAND_FRACTION)
        top = int(np.argmin(same)) if not same.all() else h
        bottom = int(np.argmin(same[::-1])) if not same.all() else h
        return min(top, limit), min(bottom, limit)

    @classmethod
    def _find_shift(cls, ph, pi, ch, expected) -> int | None:
        n = len(ph)
        min_overlap = max(20, n // 20)
        scored: list[tuple[float, int, int]] = []          # (score, shift, informative rows)
        for dy in range(0, n - min_overlap + 1):
            info = pi[dy:]
            k = int(info.sum())
            if k >= MIN_INFO_ROWS:
                scored.append((float((ph[dy:][info] == ch[:n - dy][info]).mean()), dy, k))
        return cls._pick(scored, expected)

    @classmethod
    def _find_shift_tolerant(cls, pg, cg, pi, expected) -> int | None:
        n = len(pg)
        min_overlap = max(20, n // 20)
        scored: list[tuple[float, int, int]] = []
        for dy in range(0, n - min_overlap + 1):
            info = pi[dy:]
            k = int(info.sum())
            if k >= MIN_INFO_ROWS:
                close = np.abs(pg[dy:][info] - cg[:n - dy][info]).mean(axis=1) < ROW_TOL
                scored.append((float(close.mean()), dy, k))
        return cls._pick(scored, expected)

    @staticmethod
    def _pick(scored, expected) -> int | None:
        best = [c for c in scored if c[0] >= MIN_SCORE]
        if not best and scored:
            # something moved over part of the view (a popup bar, a hover effect): accept the
            # best shift only if it clearly beats every shift that isn't right next to it
            top = max(scored)
            rivals = [c[0] for c in scored if abs(c[1] - top[1]) > NEAR]   # a text line is many equal rows
            if top[0] >= LOOSE_SCORE and top[0] - max(rivals, default=0.0) >= LOOSE_MARGIN:
                best = [top]
        if not best:
            return None
        top_score = max(sc for sc, _, _ in best)
        tied = [(dy, k) for sc, dy, k in best if sc >= top_score - 0.01]
        if expected is not None:
            return min(tied, key=lambda t: (abs(t[0] - expected), t[0]))[0]
        return max(tied, key=lambda t: (t[1], -t[0]))[0]

    def _note_scrollbar(self, prev_band, cur_band, shift) -> None:
        """A scrollbar thumb moves at its own pace: at the right edge, columns that don't follow
        the content are cut from the result."""
        w = prev_band.shape[1]
        zone = min(EDGE_ZONE, w // 4)
        a = prev_band[shift:].astype(np.int16)
        b = cur_band[:cur_band.shape[0] - shift].astype(np.int16)
        if a.shape[0] == 0:
            return
        miss = (np.abs(a - b).max(axis=2) > 12).mean(axis=0)          # per column
        inner = float(np.median(miss[w // 4:w - zone])) if w - zone > w // 4 else 0.0
        # only columns that disagree clearly more than the page itself (a popup over the
        # whole width is not a scrollbar)
        bad = (miss[w - zone:] > 0.05) & (miss[w - zone:] > 3 * inner + 0.02)
        if bad.any():
            self.crop_right = max(self.crop_right, zone - int(np.argmax(bad)))

    def result(self) -> np.ndarray:
        if self.first is None:
            return np.zeros((1, 1, 3), np.uint8)
        if not self.pieces:
            out = self.first
        else:
            h = self.first.shape[0]
            foot = self.bottom or 0
            out = np.vstack([self.first[:h - foot]] + self.pieces + ([self.last[h - foot:]] if foot else []))
        out = out[:self._cap()]
        left, right = self._column_span(out.shape[1])
        if self.crop_right:
            right = min(right, out.shape[1] - self.crop_right)
        if right - left >= 16:
            out = out[:, left:right]
        return np.ascontiguousarray(out)
