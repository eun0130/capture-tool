"""OCR of images larger than the recognizer's 2000 px limit (scroll captures, 4K screens):
recognized in overlapping tiles at full resolution, each line exactly once."""
import sys

import numpy as np
import pytest

from capture_tool.core.ocr import OcrEngine, tiles
from tests.test_ocr import FakeResult, quad


class Recorder:
    """Fake engine: 'sees' text lines placed on a big virtual page, per tile."""

    def __init__(self, lines):
        self.lines = lines            # [(text, x, y, w, h)] in full-image coordinates
        self.calls = []

    def factory(self):
        return self.run

    def run(self, img):
        x0, y0 = img.meta                     # where this tile sits in the full image
        h, w = img.shape[:2]
        self.calls.append((x0, y0, w, h))
        items = [(t, quad(x - x0, y - y0, lw, lh), 0.95) for t, x, y, lw, lh in self.lines
                 if x >= x0 and y >= y0 and x + lw <= x0 + w and y + lh <= y0 + h]
        return FakeResult(items)


class Tagged(np.ndarray):
    pass


def tagging_engine(rec):
    """Wrap so every tile carries its offset (the engine receives views of the big image)."""
    eng = OcrEngine(rec.factory)
    orig = eng._run_tile

    def run_tile(engine, img, x0, y0):
        t = np.ascontiguousarray(img).view(Tagged)
        t.meta = (x0, y0)
        return orig(engine, t, x0, y0)
    eng._run_tile = run_tile
    return eng


def inked(lines, h=9000, w=1300):
    """White page with a dark block wherever a (fake) text line is."""
    img = np.full((h, w, 3), 255, np.uint8)
    for _, x, y, lw, lh in lines:
        img[y:y + lh, x:x + lw] = 0
    return img


def test_TILE_01_small_image_is_one_call():
    assert tiles(1500, 1900) == [(0, 0, 1500, 1900)]


def test_TILE_02_tall_image_tiles_overlap_and_stay_within_limits():
    t = tiles(1300, 9000)
    assert len(t) > 4 and all(h <= 1900 and w == 1300 for _, _, w, h in t)
    ys = [y for _, y, _, _ in t]
    assert ys[0] == 0 and t[-1][1] + t[-1][3] == 9000
    assert all(b - a <= 1900 - 200 for a, b in zip(ys, ys[1:]))       # overlap >= 200 px


def test_TILE_03_very_wide_image_also_tiled_across():
    t = tiles(6000, 1000)
    assert len(t) >= 2 and all(w <= 3800 for _, _, w, _ in t) and t[-1][0] + t[-1][2] == 6000


def test_TILE_04_lines_mapped_back_and_counted_once():
    lines = [(f"줄{i}", 40, 150 + i * 237, 300, 30) for i in range(36)]          # some fall in overlaps
    rec = Recorder(lines)
    got = tagging_engine(rec).recognize(inked(lines))
    assert [l.text for l in got] == [t for t, *_ in lines]
    assert [l.box[1] for l in got] == [y for _, _, y, _, _ in lines]
    assert len(rec.calls) > 4


def test_TILE_05_line_exactly_on_a_tile_boundary():
    t = tiles(1300, 9000)
    boundary = t[1][1] + 100                                   # middle of the first overlap
    lines = [("경계", 40, boundary - 15, 300, 30)]
    rec = Recorder(lines)
    got = tagging_engine(rec).recognize(inked(lines))
    assert [l.text for l in got] == ["경계"]


def _real_ok():
    from capture_tool.core.ocr import missing_models, REQUIRED_MODELS
    return not missing_models(REQUIRED_MODELS)


@pytest.mark.slow
@pytest.mark.skipif(not _real_ok(), reason="OCR models missing")
def test_TILE_REAL_01_real_ocr_reads_every_line_of_a_7000px_page(qt_app):
    from tests.tallocr import tall_page
    img, want = tall_page()
    got = [l.text.replace(" ", "") for l in OcrEngine().recognize(img)]
    found = [w for w in want if any(w.replace(" ", "") in g for g in got)]
    assert len(found) >= len(want) - 1, (want, got)


# --- v0.6.1: speed -------------------------------------------------------------------------------------
def test_TILE_06_thread_count_scales_with_the_pc_but_never_takes_every_core():
    from capture_tool.core.ocr import ocr_threads
    assert ocr_threads(2) == 1 and ocr_threads(4) == 2 and ocr_threads(8) == 4
    assert ocr_threads(16) == 8 and ocr_threads(32) == 8 and ocr_threads(None) >= 1


def test_TILE_07_blank_parts_of_a_tall_image_are_not_sent_to_the_recognizer():
    lines = [("위", 40, 200, 300, 30), ("아래", 40, 8500, 300, 30)]
    rec = Recorder(lines)
    img = np.full((9000, 1300, 3), 255, np.uint8)
    for _, x, y, w, h in lines:
        img[y:y + h, x:x + w] = 0                       # ink where the text is; the rest is white
    got = tagging_engine(rec).recognize(img)
    assert [l.text for l in got] == ["위", "아래"]
    assert sum(h for _, _, _, h in rec.calls) < 9000 * 0.5   # most of the white page skipped


def test_TILE_08_tile_trimmed_to_its_ink_keeps_coordinates():
    rec = Recorder([("가운데", 600, 4000, 200, 30)])
    img = np.full((9000, 1300, 3), 255, np.uint8)
    img[4000:4030, 600:800] = 0
    got = tagging_engine(rec).recognize(img)
    assert [(l.text, l.box[:2]) for l in got] == [("가운데", (600, 4000))]


# --- v0.8.31: a 4K screen is cut into even tiles, not four almost-whole copies ---------------------
def test_TILE_09_4k_tiles_are_even_so_little_is_read_twice():
    from capture_tool.core.ocr import TILE_H, TILE_OVERLAP, TILE_W
    t = tiles(3840, 2160)
    assert len(t) == 4 and all(w <= TILE_W and h <= TILE_H for _, _, w, h in t)
    assert sum(w * h for _, _, w, h in t) <= 3840 * 2160 * 1.3          # was 3.3x
    xs, ys = sorted({x for x, _, _, _ in t}), sorted({y for _, y, _, _ in t})
    tw, th = t[0][2], t[0][3]
    assert xs[0] == 0 and ys[0] == 0 and xs[-1] + tw == 3840 and ys[-1] + th == 2160
    assert all(a + tw - b >= TILE_OVERLAP for a, b in zip(xs, xs[1:]))
    assert all(a + th - b >= TILE_OVERLAP for a, b in zip(ys, ys[1:]))


def test_TILE_10_every_point_is_owned_by_exactly_one_tile():
    from capture_tool.core.ocr import _owned
    w, h = 3840, 2160
    t = tiles(w, h)
    for cx, cy in [(0, 0), (1900, 1000), (2000, 1100), (3839, 2159), (1920, 1080), (100, 2000)]:
        owners = [1 for x0, y0, tw, th in t
                  if (lambda o: o[0] <= cx < o[2] and o[1] <= cy < o[3])(_owned(x0, y0, tw, th, w, h))]
        assert len(owners) == 1, (cx, cy)
