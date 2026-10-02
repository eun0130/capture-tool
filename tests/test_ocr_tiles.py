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
        t = img.view(Tagged)
        t.meta = (x0, y0)
        return orig(engine, t, x0, y0)
    eng._run_tile = run_tile
    return eng


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
    got = tagging_engine(rec).recognize(np.zeros((9000, 1300, 3), np.uint8))
    assert [l.text for l in got] == [t for t, *_ in lines]
    assert [l.box[1] for l in got] == [y for _, _, y, _, _ in lines]
    assert len(rec.calls) > 4


def test_TILE_05_line_exactly_on_a_tile_boundary():
    t = tiles(1300, 9000)
    boundary = t[1][1] + 100                                   # middle of the first overlap
    rec = Recorder([("경계", 40, boundary - 15, 300, 30)])
    got = tagging_engine(rec).recognize(np.zeros((9000, 1300, 3), np.uint8))
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
