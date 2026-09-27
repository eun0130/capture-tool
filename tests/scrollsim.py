"""A fake scrollable page for scroll-capture tests: a tall picture seen through a viewport, with
an optional sticky header/footer and a scrollbar whose thumb moves (like a browser)."""
from __future__ import annotations

import cv2
import numpy as np


def make_page(h=3000, w=480, seed=1, blank_gap=None) -> np.ndarray:
    """Document-like content: text-ish lines, boxes, varied colors; unique at every height."""
    rng = np.random.default_rng(seed)
    page = np.full((h, w, 3), 255, np.uint8)
    y = 10
    while y < h - 30:
        if blank_gap and blank_gap[0] <= y < blank_gap[1]:
            y = blank_gap[1]
            continue
        kind = rng.integers(0, 4)
        if kind == 0:   # a "text line": dark dashes of random lengths
            x = 20
            while x < w - 60:
                ln = int(rng.integers(12, 60))
                cv2.rectangle(page, (x, y), (min(w - 30, x + ln), y + 9), (40, 40, 40), -1)
                x += ln + int(rng.integers(6, 14))
            y += 22
        elif kind == 1:  # a colored box with a label
            c = tuple(int(v) for v in rng.integers(60, 230, 3))
            bh = int(rng.integers(30, 90))
            cv2.rectangle(page, (30, y), (w - 60, y + bh), c, -1)
            cv2.putText(page, f"row {y}", (40, y + bh // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            y += bh + 12
        else:
            cv2.putText(page, f"paragraph at {y} px", (24, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (30, 30, 30), 1)
            y += 26
    return page


class FakePage:
    """Viewport of `vh` rows over `page`; wheel(notches) scrolls by px_per_notch (negative = down)."""

    def __init__(self, page, vh=500, px_per_notch=40, header=0, footer=0, scrollbar=0, start=0,
                 grows_to=None, stuck=False):
        self.page, self.vh = page, vh
        self.px = px_per_notch
        self.header, self.footer, self.scrollbar = header, footer, scrollbar
        self.offset = start
        self.grows_to = grows_to      # lazy loading: the page gets longer once the end is reached
        self.stuck = stuck            # a window that ignores the wheel (e.g. admin window)
        self.wheels = []
        self.grabs = 0

    @property
    def max_offset(self) -> int:
        return self.page.shape[0] - (self.vh - self.header - self.footer)

    def wheel(self, notches: int) -> None:
        self.wheels.append(notches)
        if self.stuck:
            return
        if self.grows_to and self.offset >= self.max_offset and self.page.shape[0] < self.grows_to:
            extra = make_page(self.grows_to - self.page.shape[0], self.page.shape[1], seed=99)
            self.page = np.vstack([self.page, extra])
        self.offset = int(min(max(self.offset - notches * self.px, 0), self.max_offset))

    def frame(self) -> np.ndarray:
        self.grabs += 1
        w = self.page.shape[1]
        body = self.vh - self.header - self.footer
        out = np.empty((self.vh, w + self.scrollbar, 3), np.uint8)
        out[self.header:self.header + body, :w] = self.page[self.offset:self.offset + body]
        if self.header:
            out[:self.header, :w] = (200, 120, 40)
            cv2.putText(out, "STICKY HEADER", (10, self.header - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1)
        if self.footer:
            out[self.vh - self.footer:, :w] = (60, 60, 60)
        if self.scrollbar:
            out[:, w:] = (235, 235, 235)
            total = self.page.shape[0]
            t0 = int(self.vh * self.offset / total)
            t1 = int(self.vh * (self.offset + body) / total)
            out[t0:max(t0 + 20, t1), w + 2:w + self.scrollbar - 2] = (120, 120, 120)
        return out

    def expected(self, top=0, bottom=None) -> np.ndarray:
        """What a perfect capture of page rows [top, bottom) looks like (no scrollbar)."""
        bottom = self.page.shape[0] if bottom is None else bottom
        w = self.page.shape[1]
        parts = []
        if self.header:
            parts.append(self.frame()[:self.header, :w])
        parts.append(self.page[top:bottom])
        if self.footer:
            parts.append(self.frame()[self.vh - self.footer:, :w])
        return np.vstack(parts)
