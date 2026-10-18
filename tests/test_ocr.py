import threading

import numpy as np
import pytest

from capture_tool.core.ocr import MARGIN, OcrEngine, OcrLine, OcrUnavailable, full_text, select_text
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


def test_OCR_02c_latin_model_loaded_only_when_needed():
    loads = []
    eng = OcrEngine(make_factory([("요청 접수", quad(0, 0, 50, 20), 0.9)]),
                    secondary_factory=lambda: loads.append(1) or FakeLatin({}),
                    secondary_call=lambda e, crop, text: None)
    eng.warmup().join(5)
    eng.recognize(IMG)
    assert loads == []            # Korean-only screens never pay for the Latin model


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


# --- drag to copy part of the recognized text -------------------------------------------------

def test_SEL_01_drag_over_part_of_a_line_copies_those_characters():
    lines = [OcrLine("0123456789", (100, 10, 200, 20), 0.9)]     # 20 px per character
    assert select_text(lines, (140, 0, 60, 40)) == "234"


def test_SEL_02_drag_over_several_lines():
    lines = [OcrLine("첫 번째 줄", (10, 10, 120, 20), 0.9), OcrLine("두 번째 줄", (10, 40, 120, 20), 0.9),
             OcrLine("세 번째 줄", (10, 70, 120, 20), 0.9)]
    assert select_text(lines, (0, 0, 300, 65)) == "첫 번째 줄\n두 번째 줄"


def test_SEL_03_nothing_under_the_drag():
    lines = [OcrLine("abc", (10, 10, 30, 20), 0.9)]
    assert select_text(lines, (200, 200, 10, 10)) == ""
    assert select_text([], (0, 0, 10, 10)) == ""


def test_SEL_04_same_row_segments_joined_with_space():
    lines = [OcrLine("이름", (10, 10, 40, 20), 0.9), OcrLine("홍길동", (100, 12, 60, 20), 0.9)]
    assert select_text(lines, (0, 0, 300, 40)) == "이름 홍길동"


# --- second recognizer for Latin-script languages (French, Spanish, German, ...) ---------

class FakeLatin:
    def __init__(self, answers, fail=False):
        self.answers = answers        # text-from-primary -> (text, score)
        self.calls = []
        self.fail = fail

    def factory(self):
        if self.fail:
            raise RuntimeError("latin model missing")
        return self

    def __call__(self, crop, primary_text):
        self.calls.append(primary_text)
        return self.answers.get(primary_text)


def engine_with(items, latin):
    return OcrEngine(make_factory(items), secondary_factory=latin.factory,
                     secondary_call=lambda eng, crop, text: eng(crop, text))


def test_OCR_06_latin_line_uses_better_second_reading():
    items = [("Le garcon mange", quad(10, 10, 200, 20), 0.90)]
    latin = FakeLatin({"Le garcon mange": ("Le garçon mange", 0.97)})
    lines = engine_with(items, latin).recognize(IMG)
    assert [l.text for l in lines] == ["Le garçon mange"]
    assert lines[0].box == (10, 10, 200, 20)


def test_OCR_07_hangul_lines_never_sent_to_latin_model():
    items = [("요청 접수 Hello", quad(10, 10, 200, 20), 0.95), ("Très bien", quad(10, 40, 100, 20), 0.8)]
    latin = FakeLatin({"Très bien": ("Très bien", 0.95)})
    engine_with(items, latin).recognize(IMG)
    assert latin.calls == ["Très bien"]


def test_OCR_08_keep_primary_when_second_is_worse():
    items = [("Hello World", quad(10, 10, 200, 20), 0.99)]
    latin = FakeLatin({"Hello World": ("He1lo Wor1d", 0.70)})
    assert [l.text for l in engine_with(items, latin).recognize(IMG)] == ["Hello World"]


def test_OCR_09_digits_only_line_skipped():
    items = [("010-1234-5678", quad(10, 10, 200, 20), 0.97)]
    latin = FakeLatin({})
    engine_with(items, latin).recognize(IMG)
    assert latin.calls == []


def test_OCR_10_latin_model_failure_is_harmless():
    items = [("Le garcon", quad(10, 10, 200, 20), 0.9)]
    latin = FakeLatin({}, fail=True)
    eng = engine_with(items, latin)
    assert [l.text for l in eng.recognize(IMG)] == ["Le garcon"]
    assert [l.text for l in eng.recognize(IMG)] == ["Le garcon"]   # still fine on the next call


def test_OCR_11_second_returns_nothing_keeps_primary():
    items = [("Hola", quad(10, 10, 60, 20), 0.9)]
    latin = FakeLatin({"Hola": None})
    assert [l.text for l in engine_with(items, latin).recognize(IMG)] == ["Hola"]


def _sim(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()


@pytest.mark.slow
def test_OCR_12_real_mixed_korean_french_spanish_german(qt_app):
    from tests.render import render_text
    fr = "Le garçon mange une crème brûlée à côté de l'église."
    es = "El niño comió piña en la montaña. ¿Dónde está la estación?"
    de = "Größe, Straße und Übung für Mädchen."
    ko = "요청 접수 검토 승인 010-1234-5678"
    img = render_text([ko, fr, es, de], width=1100, size=22)
    text = full_text(OcrEngine().recognize(img))
    got = text.split("\n")
    assert got[0].replace(" ", "") == ko.replace(" ", "")
    joined = " ".join(got[1:])
    for word in ["garçon", "crème", "brûlée", "côté", "église", "niño", "piña", "montaña", "¿Dónde",
                 "estación", "Größe", "Straße", "Übung", "Mädchen"]:
        assert word in joined, (word, joined)


@pytest.mark.slow
def test_OCR_13_real_spreadsheet_screenshot_to_cells(qt_app):
    """Excel-like screenshot (light gray grid, Korean + numbers) -> exact cells."""
    import numpy as np
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    from capture_tool.core.table import detect_grid, grid_from_cells
    from tests.render import _font

    rows = [["품목", "수량", "단가", "금액"], ["사과", "3", "1,200", "3,600"],
            ["배", "", "2,500", "0"], ["합계", "", "", "3,600"]]
    cw, rh, x0, y0 = 150, 34, 10, 10
    W, H = x0 * 2 + cw * 4 + 1, y0 * 2 + rh * 4 + 1
    img = QImage(W, H, QImage.Format_RGB888)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QPen(QColor(212, 212, 212), 1))
    for r in range(5):
        p.drawLine(x0, y0 + r * rh, x0 + 4 * cw, y0 + r * rh)
    for c in range(5):
        p.drawLine(x0 + c * cw, y0, x0 + c * cw, y0 + 4 * rh)
    p.setFont(_font(15))
    p.setPen(QColor("black"))
    for r, row in enumerate(rows):
        for c, t in enumerate(row):
            align = Qt.AlignVCenter | (Qt.AlignRight if c > 0 else Qt.AlignLeft)
            p.drawText(QRect(x0 + c * cw + 6, y0 + r * rh, cw - 12, rh), align, t)
    p.end()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine())[:, :W * 3]
    bgr = arr.reshape(H, W, 3)[:, :, ::-1].copy()
    xs, ys = detect_grid(bgr)
    lines = OcrEngine().recognize(bgr)
    grid = grid_from_cells([(l.text, *l.box) for l in lines], xs, ys)
    assert grid == rows


@pytest.mark.slow
def test_OCR_real_engine_korean(qt_app):
    from tests.render import render_text
    img = render_text(["요청 접수 · 검토 · 승인", "담당: 홍길동 010-1234-5678", "Hello World 2026"])
    lines = OcrEngine().recognize(img)
    text = full_text(lines).replace(" ", "")
    assert "요청접수" in text and "검토" in text and "승인" in text
    assert "010-1234-5678" in text
    assert "HelloWorld2026" in text


def test_OCR_FT_01_full_text_joins_segments_on_the_same_row():
    from capture_tool.core.ocr import OcrLine, full_text
    words = [OcrLine("starts", (300, 12, 90, 30), 0.9), OcrLine("The", (20, 10, 60, 30), 0.9),
             OcrLine("meeting", (100, 11, 150, 30), 0.9), OcrLine("tomorrow.", (20, 60, 150, 30), 0.9)]
    assert full_text(words) == "The meeting starts\ntomorrow."
    assert full_text([]) == ""


def _col(text, x, y, w):
    return OcrLine(text, (x, y, w, 26), 0.9)


def test_OCR_14_two_text_columns_are_read_column_by_column():
    """BUG-123: a two-column page (an article, a PDF paper) came out row by row, the left and
    right lines interleaved. A gutter no line crosses with wrapped text on both sides is a
    column boundary: left column top to bottom, then the right one. A title across both columns
    separates what is above it from what is below."""
    from capture_tool.core.ocr import reading_order
    title = _col("보고서 제목 한 줄", 20, 20, 460)
    left = [_col(f"왼쪽 단 {i}째 줄의 글입니다", 20, 60 + 34 * i, 250 if i < 4 else 170) for i in range(5)]
    right = [_col(f"오른쪽 단 {i}째 줄의 글입니다", 300, 62 + 34 * i, 250 if i < 4 else 120) for i in range(5)]
    footer = _col("끝: 두 단에 걸친 맺음말", 20, 240, 500)
    mixed = [right[3], left[0], footer, right[0], left[4], title, left[2], right[4], left[1], right[1], right[2], left[3]]
    want = [title.text] + [l.text for l in left] + [l.text for l in right] + [footer.text]
    assert [l.text for l in reading_order(mixed)] == want
    assert full_text(mixed) == "\n".join(want)


def test_OCR_15_a_label_list_and_short_columns_are_still_read_row_by_row():
    """A form (label, value) has a gutter too, but its label column is narrow; code with aligned
    columns has ragged lines: both stay rows."""
    from capture_tool.core.ocr import reading_order
    form = []
    for i, (k, v) in enumerate([("이름", "홍길동"), ("부서", "영업팀"), ("직급", "대리"), ("전화", "010-1234-5678"),
                                ("주소", "서울시 강남구 테헤란로 1"), ("비고", "없음")]):
        form += [_col(v, 160, 20 + 34 * i, 12 * len(v)), _col(k, 20, 20 + 34 * i, 50)]
    assert [l.text for l in reading_order(form)] == [t for i in range(6) for t in (form[2 * i + 1].text, form[2 * i].text)]
    two = [_col("이름", 20, 20, 50), _col("홍길동", 300, 20, 250), _col("부서", 20, 54, 50), _col("영업팀", 300, 54, 250)]
    assert [l.text for l in reading_order(two)] == ["이름", "홍길동", "부서", "영업팀"]
    widths = [250, 90, 180, 60, 250, 120, 40, 200]       # ragged: nothing wraps at a column edge
    code = [_col(f"left {i}", 20, 20 + 34 * i, widths[i]) for i in range(8)] + \
           [_col(f"right {i}", 330, 20 + 34 * i, widths[7 - i]) for i in range(8)]
    assert [l.text for l in reading_order(code)] == [t for i in range(8) for t in (f"left {i}", f"right {i}")]


def test_OCR_16_select_text_cuts_at_the_readers_word_boxes():
    """BUG-124: characters were placed evenly over the line box, so in mixed Korean/Latin text
    (Korean letters twice as wide) a drag over "hello" picked "ello". The reader's word boxes
    place every letter; text the fixes changed (a space put back) is aligned to them."""
    words = (("안녕", (20.0, 22.0, 60.0, 46.0)), ("hello", (65.0, 22.0, 114.0, 46.0)), ("세계", (119.0, 22.0, 154.0, 46.0)))
    line = OcrLine("안녕 hello 세계", (20, 22, 134, 24), 0.9, words)
    assert select_text([line], (64, 10, 51, 40)) == "hello"
    assert select_text([line], (118, 10, 40, 40)) == "세계"
    assert select_text([line], (20, 10, 41, 40)) == "안녕"
    assert select_text([line], (100, 10, 30, 40)) == "o 세"
    plain = OcrLine("안녕 hello 세계", (20, 22, 134, 24), 0.9)       # no word boxes: evenly as before
    assert select_text([plain], (64, 10, 51, 40)) == "ello"
    fixed = OcrLine("안녕 hel lo 세계", (20, 22, 134, 24), 0.9, words)   # text no longer equal to the words
    assert select_text([fixed], (64, 10, 51, 40)) == "hel lo"
    assert select_text([OcrLine("", (20, 22, 134, 24), 0.9, words)], (0, 0, 500, 500)) == ""


def _bar(t, h, w):
    """A white h x w picture with t rows of black in the middle: letters t px tall."""
    img = np.full((h, w, 3), 255, np.uint8)
    top = (h - t) // 2
    img[top:top + t, 10:w - 10] = 0
    return img


def test_OCR_17_a_big_title_line_gets_a_frame_that_keeps_its_letters_readable():
    """BUG-122: the reader scales a picture's shorter side up to 736 px before finding text, so a
    tight crop of one 36 pt title (53 px, letters 34 px) with the 24 px frame became 7x: letters
    of 250 px that came back as "매 현 호 Q3 2026 L7". When the letters would come out taller
    than 160 px the frame grows so they land near 128 px; small text (and two lines of normal
    text in a 98 px crop) keeps the 24 px frame it was tuned with."""
    from capture_tool.core.ocr import DET_SIDE, TITLE_LETTER_PX, frame_width, text_height
    assert text_height(_bar(23, 98, 256)) == 23
    ruled = _bar(23, 98, 256)
    ruled[5:93, 120:122] = 0                                     # a vertical rule across both lines
    assert text_height(ruled) == 23 and frame_width(ruled) == 24
    assert frame_width(_bar(13, 23, 300)) == 24 and frame_width(_bar(15, 26, 300)) == 24
    assert frame_width(_bar(23, 98, 256)) == 24                  # ST-08: 22 pt mono, two lines
    assert frame_width(np.full((53, 557, 3), 255, np.uint8)) == 24   # nothing written
    for t, h in ((19, 31), (23, 37), (34, 53), (45, 68), (60, 90)):
        m = frame_width(_bar(t, h, 600))
        assert m > 24 and abs(t * DET_SIDE / (h + 2 * m) - TITLE_LETTER_PX) <= 4, (t, h, m)
    assert frame_width(_bar(45, 68, 40)) > frame_width(_bar(45, 68, 600))   # the shorter side counts
    eng = OcrEngine(make_factory([("제목", quad(100, 100, 300, 50), 0.9)]), margin=MARGIN)
    seen = []
    eng._run_tile = lambda engine, img, x0, y0: seen.append((img.shape, x0, y0)) or []
    title = _bar(47, 53, 557)
    eng.recognize(title)
    m = frame_width(title)
    assert m == 109 and seen == [((53 + 2 * m, 557 + 2 * m, 3), -m, -m)]
