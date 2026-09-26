import threading

import numpy as np
import pytest

from capture_tool.core.ocr import OcrEngine, OcrLine, OcrUnavailable, full_text
from capture_tool.core.redact import char_boxes


class FakeResult:
    def __init__(self, items):
        self.boxes = np.array([b for _, b, _ in items], float) if items else None
        self.txts = tuple(t for t, _, _ in items) if items else None
        self.scores = tuple(s for _, _, s in items) if items else None


def quad(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def make_factory(items, counter=None):
    def factory():
        if counter is not None:
            counter.append(1)
        return lambda img: FakeResult(items)
    return factory


IMG = np.zeros((100, 300, 3), np.uint8)


def test_OCR_01_reading_order():
    items = [("둘째 줄 오른쪽", quad(150, 52, 100, 20), 0.9), ("첫 줄", quad(10, 10, 80, 20), 0.95),
             ("둘째 줄 왼쪽", quad(10, 50, 100, 20), 0.9)]
    lines = OcrEngine(make_factory(items)).recognize(IMG)
    assert [l.text for l in lines] == ["첫 줄", "둘째 줄 왼쪽", "둘째 줄 오른쪽"]
    assert lines[0].box == (10, 10, 80, 20)


def test_OCR_02_loaded_once():
    calls = []
    eng = OcrEngine(make_factory([("a", quad(0, 0, 5, 5), 0.9)], calls))
    eng.recognize(IMG)
    eng.recognize(IMG)
    assert len(calls) == 1


def test_OCR_02b_warmup_in_background():
    calls = []
    eng = OcrEngine(make_factory([], calls))
    t = eng.warmup()
    assert isinstance(t, threading.Thread)
    t.join(5)
    assert len(calls) == 1 and eng.ready


def test_OCR_03_load_failure():
    def bad():
        raise RuntimeError("model file missing")
    eng = OcrEngine(bad)
    with pytest.raises(OcrUnavailable):
        eng.recognize(IMG)
    assert not eng.ready
    eng.warmup().join(5)  # warmup must not raise
    with pytest.raises(OcrUnavailable):
        eng.recognize(IMG)


def test_OCR_04_empty_inputs():
    eng = OcrEngine(make_factory([]))
    assert eng.recognize(IMG) == []
    assert eng.recognize(np.zeros((0, 0, 3), np.uint8)) == []
    assert eng.recognize(None) == []


def test_OCR_04b_low_confidence_dropped():
    items = [("good", quad(0, 0, 50, 20), 0.9), ("noise", quad(0, 40, 50, 20), 0.2)]
    assert [l.text for l in OcrEngine(make_factory(items)).recognize(IMG)] == ["good"]


def test_OCR_05_full_text():
    lines = [OcrLine("a", (0, 0, 10, 10), 1.0), OcrLine("b", (0, 20, 10, 10), 1.0)]
    assert full_text(lines) == "a\nb"
    assert full_text([]) == ""


def test_char_boxes_proportional():
    boxes = char_boxes("abcdefghij", (100, 10, 200, 20), [(2, 5)])
    assert boxes == [(140, 10, 60, 20)]
    assert char_boxes("", (0, 0, 10, 10), [(0, 1)]) == []


@pytest.mark.slow
def test_OCR_real_engine_korean(qt_app):
    from tests.render import render_text
    img = render_text(["요청 접수 · 검토 · 승인", "담당: 홍길동 010-1234-5678", "Hello World 2026"])
    lines = OcrEngine().recognize(img)
    text = full_text(lines).replace(" ", "")
    assert "요청접수" in text and "검토" in text and "승인" in text
    assert "010-1234-5678" in text
    assert "HelloWorld2026" in text
