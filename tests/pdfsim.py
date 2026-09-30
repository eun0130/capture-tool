"""A fake PDF viewer for scroll-capture tests: toolbar on top, a thumbnail sidebar that does
NOT scroll (its highlight follows the current page), pages with gray gaps and margins, photos
that render a little differently every frame, pages drawn late, a page-number badge."""
from __future__ import annotations

import cv2
import numpy as np

from tests.scrollsim import make_page

GRAY = (60, 60, 60)          # viewer background around pages
SIDEBAR = (48, 36, 40)       # thumbnail panel (a colour that never occurs in pages)
MARKERS = [(216, 100, 28), (49, 49, 224), (68, 158, 47), (0, 140, 240), (232, 72, 112), (153, 133, 12)]


def pdf_page(w: int, h: int, n: int, blank=False, photo=True, table=True) -> np.ndarray:
    page = np.full((h, w, 3), 255, np.uint8)
    page[:30] = MARKERS[n % len(MARKERS)]                   # page marker bar
    if blank:
        return page
    body = make_page(h - 40, w - 60, seed=n + 1)
    page[40:, 30:w - 30] = body
    if photo:                                               # photo-like block
        y0 = h // 3
        yy, xx = np.mgrid[0:160, 0:w - 120].astype(np.float32)
        for c in range(3):
            page[y0:y0 + 160, 60:w - 60, c] = (128 + 80 * np.sin(xx / (13 + 5 * c) + yy / 21)).astype(np.uint8)
    if table:                                               # repeating ruled rows
        y0 = 2 * h // 3
        for r in range(8):
            page[y0 + r * 24, 40:w - 40] = (136, 136, 136)
    return page


class PdfView:
    def __init__(self, pages=5, page_w=420, page_h=700, gap=16, margin=50, vh=520, toolbar=40, sidebar=0,
                 px_per_notch=60, jitter_photo=False, lazy_grabs=0, badge=False, blank=(), start=0):
        self.pages = [pdf_page(page_w, page_h, n, blank=n in blank) for n in range(pages)]
        self.page_h, self.gap, self.margin = page_h, gap, margin
        parts = []
        for i, p in enumerate(self.pages):
            if i:
                parts.append(np.full((gap, page_w, 3), GRAY, np.uint8))
            parts.append(p)
        doc = np.vstack(parts)
        side = np.full((doc.shape[0], margin, 3), GRAY, np.uint8)
        self.doc = np.hstack([side, doc, side])              # what scrolls
        self.vh, self.toolbar, self.sidebar = vh, toolbar, sidebar
        self.px, self.offset = px_per_notch, start
        self.jitter_photo, self.lazy_grabs, self.badge = jitter_photo, lazy_grabs, badge
        self.rng = np.random.default_rng(7)
        self.wheels, self._lazy_left, self._shown_to = [], 0, start + vh - toolbar
        self.grabs = 0

    @property
    def view_h(self) -> int:
        return self.vh - self.toolbar

    @property
    def max_offset(self) -> int:
        return self.doc.shape[0] - self.view_h

    def current_page(self) -> int:
        return min(len(self.pages) - 1, self.offset // (self.page_h + self.gap))

    def wheel(self, notches: int) -> None:
        self.wheels.append(notches)
        before = self.offset
        self.offset = int(min(max(self.offset - notches * self.px, 0), self.max_offset))
        if self.offset > before and self.lazy_grabs:
            self._lazy_left = self.lazy_grabs

    def frame(self) -> np.ndarray:
        self.grabs += 1
        dw = self.doc.shape[1]
        out = np.empty((self.vh, self.sidebar + dw, 3), np.uint8)
        body = self.doc[self.offset:self.offset + self.view_h].copy()
        if self._lazy_left:                                  # newly exposed rows not drawn yet
            self._lazy_left -= 1
            body[self.view_h // 2:, self.margin:dw - self.margin] = 255
        if self.jitter_photo:                                # photos re-rendered slightly differently
            noise = self.rng.integers(-5, 6, body.shape)
            mask = (body.std(axis=2) > 25)[..., None]
            body = np.where(mask, np.clip(body.astype(int) + noise, 0, 255), body).astype(np.uint8)
        out[self.toolbar:, self.sidebar:] = body
        out[:self.toolbar] = (40, 40, 40)
        cv2.putText(out, "sample.pdf", (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1)
        if self.sidebar:                                     # thumbnails; highlight = current page
            out[self.toolbar:, :self.sidebar] = SIDEBAR
            for i in range(len(self.pages)):
                y = self.toolbar + 10 + i * 90
                if y + 80 > self.vh:
                    break
                thumb = cv2.resize(self.pages[i], (self.sidebar - 40, 80))
                out[y:y + 80, 20:self.sidebar - 20] = thumb
                if i == self.current_page():
                    cv2.rectangle(out, (16, y - 4), (self.sidebar - 16, y + 84), (255, 180, 80), 3)
        if self.badge:                                       # "3 / 5" pill while scrolling
            x = self.sidebar + dw - 110
            cv2.rectangle(out, (x, self.toolbar + 10), (x + 90, self.toolbar + 40), (30, 30, 30), -1)
            cv2.putText(out, f"{self.current_page() + 1} / {len(self.pages)}", (x + 12, self.toolbar + 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        return out


def marker_sequence(img: np.ndarray) -> list[int]:
    """Page numbers whose marker bar appears, top to bottom (merging consecutive rows)."""
    seq = []
    col = img[:, img.shape[1] // 2].astype(int)
    for row in col:
        for i, m in enumerate(MARKERS):
            if np.abs(row - m).max() <= 6:
                if not seq or seq[-1] != i:
                    seq.append(i)
                break
    return seq
