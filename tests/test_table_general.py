"""Generalisation: the table readers on generated tables they were never tuned on. Structure must
be right, almost every character right; spacing is reported (it is the hardest part)."""
from pathlib import Path

import pytest

from capture_tool.core.box_table import find_box_table
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.table_capture import find_table, phrases_from_words
from tests.table_gen import document, score, terminal

pytestmark = pytest.mark.skipif(not (Path("C:/Windows/Fonts/gulim.ttc").exists()
                                     and Path("C:/Windows/Fonts/malgun.ttf").exists()), reason="Windows fonts")
N = 10


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


def best_table(img, ocr):
    """What the app does for the 표 button (controller._best_table)."""
    def filled(tb):
        if tb is None:
            return (-1, -1)
        n = sum(1 for r in tb.rows for c in r if c)
        return (n / max(1, len(tb.rows) * len(tb.rows[0])), n)       # complete first, then big
    t = find_table(img, [(l.text, l.box, l.score) for l in ocr.recognize(img)], [], 96)
    b = find_box_table(img, ocr.read_words, 96)
    if b is None:
        w = find_table(img, phrases_from_words(ocr.read_words(img)), [], 96)
        if filled(w) > filled(t):
            t = w
    return b if b is not None and filled(b) >= filled(t) else t


@pytest.mark.parametrize("gen", [terminal, document], ids=["terminal", "document"])
def test_GEN_01_unseen_tables(gen, ocr):
    shape = chars = nospace = 0.0
    for seed in range(N):
        img, truth = gen(seed)
        t = best_table(img, ocr)
        s = score(t.rows if t else None, truth)
        shape += s[0]
        nospace += s[2]
        chars += s[3]
    assert shape >= N - 1, shape                    # rows x columns right
    assert chars / N >= 0.97, chars / N             # characters right
    assert nospace / N >= 0.88, nospace / N         # whole cells right apart from spacing
