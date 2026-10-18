"""코드로 복사: a screenshot of code (an editor, GitHub, a diff) copied as code - line numbers and the
diff gutter (+ / -) left out, indentation restored from where the words sit on screen."""
from capture_tool.core.clipboard_payload import UNICODE
from capture_tool.core.code_copy import code_text
from capture_tool.core.ocr import OcrLine
from tests.test_app import FakeOcr, _editing, make  # noqa: F401 (fixture)

CH = 8   # px per character in the fake editor


def row(y, parts):
    """A recognized line from (x, text) word pieces at a common baseline: text joined by spaces,
    word boxes as the reader reports them."""
    words = tuple((t, (x, y, x + CH * len(t), y + 16)) for x, t in parts)
    x0, x1 = words[0][1][0], words[-1][1][2]
    return OcrLine(" ".join(t for _, t in parts), (x0, y, x1 - x0, 16), 0.95, words)


def test_CC_01_line_numbers_go_and_indentation_comes_from_the_word_positions():
    lines = [row(10, [(10, "1"), (40, "def"), (72, "main():")]),
             row(30, [(10, "2"), (72, "x"), (88, "="), (104, "1")]),
             row(50, [(10, "3"), (72, "if"), (96, "x:")]),
             row(70, [(10, "4"), (104, "return"), (160, "x")]),
             row(90, [(10, "5"), (40, "main()")])]
    assert code_text(lines) == "def main():\n    x = 1\n    if x:\n        return x\nmain()"


def test_CC_02_diff_gutter_signs_go_too():
    lines = [row(10, [(10, "12"), (36, "-"), (56, "old")]),
             row(30, [(10, "13"), (36, "+"), (56, "new")]),
             row(50, [(10, "14"), (56, "same")])]
    assert code_text(lines) == "old\nnew\nsame"


def test_CC_03_without_numbers_the_text_is_kept_with_its_own_indentation():
    lines = [row(10, [(10, "for"), (42, "i"), (58, "in"), (82, "range(3):")]),
             row(30, [(42, "print(i)")])]
    assert code_text(lines) == "for i in range(3):\n    print(i)"
    plain = [OcrLine("a = 1", (10, 10, 40, 16), 0.9), OcrLine("b = 2", (42, 30, 40, 16), 0.9)]
    assert code_text(plain) == "a = 1\n    b = 2"                 # no word boxes: the box says where it starts


def test_CC_04_typographic_quotes_and_fullwidth_signs_become_code_characters():
    lines = [row(10, [(10, "s"), (26, "="), (42, "“hi”"), (90, "＋"), (106, "‘x’")])]
    assert code_text(lines) == 's = "hi" + \'x\''


def test_CC_05_a_wrapped_line_without_a_number_keeps_its_place():
    lines = [row(10, [(10, "7"), (40, "text"), (80, "=")]),
             row(30, [(40, "\"long\"")]),
             row(50, [(10, "8"), (40, "done")])]
    assert code_text(lines) == "text =\n\"long\"\ndone"


def test_CC_06_yaml_dashes_are_not_a_diff_gutter():
    lines = [row(10, [(10, "items:")]), row(30, [(26, "-"), (42, "one")]), row(50, [(26, "-"), (42, "two")])]
    assert code_text(lines) == "items:\n  - one\n  - two"


def test_CC_07_text_mode_has_a_code_copy_button(make):
    lines = [row(110, [(110, "1"), (140, "def"), (172, "f():")]), row(130, [(110, "2"), (172, "pass")])]
    c, ov = _editing(make, ocr=FakeOcr(lines))
    ov.side_bar.trigger("text")
    b = ov.ocr_bar.buttons["code"]
    assert "코드" in b.text()
    ov.ocr_bar.trigger("code")
    assert c.clipboard.last[UNICODE] == "def f():\r\n    pass"
    assert "코드" in c.messages[-1]


def test_CC_08_a_status_line_without_a_number_does_not_shift_the_code_margin():
    """A terminal shows "Wrote 166 lines" at the left edge and the numbered code to its right:
    the code's own margin is the zero indent, and a line without a number is never negative."""
    lines = [row(10, [(10, "Wrote"), (58, "166"), (90, "lines")]),
             row(30, [(90, "7"), (113, "import"), (170, "cv2")]),
             row(50, [(90, "8"), (113, "import"), (170, "numpy")]),
             row(70, [(90, "9"), (145, "x")]),
             row(90, [(10, "+156"), (50, "lines")])]
    assert code_text(lines) == "Wrote 166 lines\nimport cv2\nimport numpy\n    x\n+156 lines"
