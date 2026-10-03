"""English inside Korean lines: the Korean model misreads short Latin words ("UI" -> "ü",
"CI" -> "cI"). Only the Latin part of such a line is read again by the Latin model; the Korean
part is never sent there, and separators like "·" are kept."""
from pathlib import Path

import numpy as np
import pytest

from capture_tool.core.ocr import OcrEngine, fix_mixed_line

IMG = np.full((200, 900, 3), 30, np.uint8)
DATA = Path(__file__).parent / "data"


class WordResult:
    def __init__(self, items):
        self.boxes = np.array([q for _, q, _, _ in items], float)
        self.txts = tuple(t for t, _, _, _ in items)
        self.scores = tuple(s for _, _, s, _ in items)
        self.word_results = tuple(tuple((w, ws, wq) for w, ws, wq in words) for _, _, _, words in items)


def quad(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class Latin:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, crop, text):
        self.calls.append(text)
        return self.answers.get(text)


def engine(items, latin):
    def factory():
        def run(img, return_word_box=False):
            return WordResult(items)
        return run
    return OcrEngine(factory, secondary_factory=lambda: latin, secondary_call=lambda eng, crop, text: eng(crop, text))


def test_MIX_01_latin_prefix_of_a_mixed_word_is_reread_keeping_separators():
    words = [("Jira·GitHub·cI·메", 0.9, quad(10, 10, 200, 25)), ("신", 0.99, quad(215, 10, 18, 25)),
             ("저", 0.99, quad(236, 10, 18, 25)), ("이벤트", 0.99, quad(270, 10, 60, 25))]
    items = [("Jira·GitHub·cI·메신저 이벤트", quad(10, 10, 320, 25), 0.95, words)]
    lat = Latin({"Jira·GitHub·cI·": ("Jira-GitHub-CI", 0.98)})
    lines = engine(items, lat).recognize(IMG)
    assert lines[0].text == "Jira·GitHub·CI·메신저 이벤트"
    assert all(not any("가" <= ch <= "힣" for ch in c) for c in lat.calls)        # Korean never sent


def test_MIX_02_whole_latin_word_in_a_korean_line():
    words = [("신고·검토", 0.99, quad(10, 10, 100, 25)), ("ü", 0.7, quad(120, 10, 20, 25))]
    items = [("신고·검토 ü", quad(10, 10, 130, 25), 0.95, words)]
    lines = engine(items, Latin({"ü": ("UI", 0.99)})).recognize(IMG)
    assert lines[0].text == "신고·검토 UI"


@pytest.mark.parametrize("answer", [("Jira-GitHub-CIXYZ", 0.99),        # a part reads quite differently
                                    ("Jira-GitHub", 0.99),              # a part is missing
                                    ("Jira-GitHub-CI", 0.60),           # clearly less sure
                                    ("", 0.99), None])
def test_MIX_03_doubtful_rereads_keep_the_first_reading(answer):
    words = [("Jira·GitHub·cI·메", 0.9, quad(10, 10, 200, 25))]
    items = [("Jira·GitHub·cI·메", quad(10, 10, 200, 25), 0.95, words)]
    lines = engine(items, Latin({"Jira·GitHub·cI·": answer})).recognize(IMG)
    assert lines[0].text == "Jira·GitHub·cI·메"


def test_MIX_04_korean_only_and_engines_without_word_boxes_are_untouched():
    from tests.test_ocr import FakeResult
    lat = Latin({})
    items = [("한글만 있는 줄", quad(10, 10, 200, 25), 0.95, [("한글만", 0.9, quad(10, 10, 60, 25))])]
    assert engine(items, lat).recognize(IMG)[0].text == "한글만 있는 줄" and lat.calls == []

    def factory():
        return lambda img: FakeResult([("요청 UI", quad(10, 10, 100, 20), 0.9)])
    e = OcrEngine(factory, secondary_factory=lambda: lat, secondary_call=lambda eng, crop, text: eng(crop, text))
    assert e.recognize(IMG)[0].text == "요청 UI"


def test_MIX_05_alignment_rules():
    assert fix_mixed_line("cI", "CI") == "CI"
    assert fix_mixed_line("Jira·GitHub·cI·", "Jira-GitHub-CI") == "Jira·GitHub·CI·"
    assert fix_mixed_line("a1·b", "A1-B") == "A1·B"
    assert fix_mixed_line("abc", "abcdef") is None
    assert fix_mixed_line("Jira·Giäub·cI·", "Jira-GitHub-CI") == "Jira·GitHub·CI·"   # one letter lost per part
    assert fix_mixed_line("ab·cd", "ab") is None
    assert fix_mixed_line("abc", "가나다") is None


@pytest.mark.parametrize("scale", [1.0, 0.75, 0.6])
def test_MIX_06_real_capture_reads_UI_and_CI(scale):
    """Bug (v0.7.1): pasted into Excel, '신고·검토 UI' became '… ü' and 'GitHub·CI' became 'cl'."""
    import cv2
    img = cv2.imread(str(DATA / "dark_mixed_table.png"))
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    text = "\n".join(l.text for l in OcrEngine().recognize(img))
    assert "UI" in text and "ü" not in text
    assert "CI" in text and "cI" not in text and "·cl" not in text, text
