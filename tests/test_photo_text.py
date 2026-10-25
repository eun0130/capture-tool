"""Text read from a photographed document (the person's rental contract): line order, the ◆
bullet, and a clearer reading of blurry print. Real OCR on tests/data/contract_photo_text.png."""
import sys
import cv2
import numpy as np
import pytest

from capture_tool.core.ocr import (OcrEngine, OcrLine, fix_false_arrows, full_text, looks_like_photo,
                                   ocr_params, reading_order)
from capture_tool.core.table_split import ocr_row_lines

PHOTO = "tests/data/contract_photo_text.png"
real_ocr = pytest.mark.skipif(not ocr_params("korean"), reason="OCR models missing")


def test_PHOTO_01_stacked_lines_with_tall_boxes_stay_in_order():
    """BUG-110: the detector's boxes on a photo are twice the line pitch, so neighbouring lines
    overlapped vertically and were sorted left-to-right as one row (3. came before 2.)."""
    two = OcrLine("2.옵션은", (14, 58, 726, 47), 0.9)
    three = OcrLine("3.월관리비", (13, 80, 738, 48), 0.9)
    assert [l.text for l in reading_order([three, two])] == ["2.옵션은", "3.월관리비"]
    assert full_text([three, two]).split("\n") == ["2.옵션은", "3.월관리비"]
    assert ocr_row_lines([(l.text, l.box) for l in (three, two)]) == ["2.옵션은", "3.월관리비"]
    # pieces of ONE row (side by side, tall boxes too) are still joined left to right
    a = OcrLine("이름", (10, 58, 100, 47), 0.9)
    b = OcrLine("김민수", (140, 62, 120, 47), 0.9)
    assert full_text([b, a]) == "이름 김민수"


def _glyph(kind: str) -> np.ndarray:
    img = np.full((30, 120, 3), 255, np.uint8)
    if kind == "diamond":
        cv2.fillPoly(img, [np.array([[14, 5], [23, 14], [14, 23], [5, 14]])], (0, 0, 0))
    elif kind == "square":
        cv2.rectangle(img, (5, 5), (23, 23), (0, 0, 0), -1)
    elif kind == "arrow":
        cv2.line(img, (4, 14), (26, 14), (0, 0, 0), 2)
        cv2.fillPoly(img, [np.array([[19, 7], [28, 14], [19, 21]])], (0, 0, 0))
    elif kind == "double":                                   # a near-square <-> with a thin shaft
        cv2.line(img, (5, 14), (23, 14), (0, 0, 0), 2)
        cv2.fillPoly(img, [np.array([[16, 8], [24, 14], [16, 20]])], (0, 0, 0))
        cv2.fillPoly(img, [np.array([[12, 8], [4, 14], [12, 20]])], (0, 0, 0))
    cv2.putText(img, "abc", (36, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return img


def test_PHOTO_02_an_arrow_the_reader_claims_must_look_like_one():
    """BUG-111: "◆ 특약" was read as "→ 특약": a solid diamond is not an arrow."""
    box = (0, 0, 120, 30)
    assert fix_false_arrows(_glyph("diamond"), "→ abc", box) == "◆ abc"
    assert fix_false_arrows(_glyph("square"), "→ abc", box) == "■ abc"
    assert fix_false_arrows(_glyph("arrow"), "→ abc", box) == "→ abc"       # a real arrow stays
    assert fix_false_arrows(_glyph("double"), "↔ abc", box) == "↔ abc"      # square-ish but a thin shaft
    assert fix_false_arrows(_glyph("arrow"), "abc", box) == "abc"            # nothing claimed: untouched


def test_PHOTO_03_a_photo_is_told_from_a_screenshot():
    assert looks_like_photo(cv2.imread(PHOTO))
    assert looks_like_photo(cv2.imread("tests/data/contract_photo_table.png"))
    for f in ("tests/data/pipe_table.png", "tests/data/adobe_banner.png", "tests/data/triangle_quiz.png"):
        assert not looks_like_photo(cv2.imread(f)), f
    assert not looks_like_photo(np.full((40, 60, 3), 240, np.uint8))


@real_ocr
@pytest.mark.skipif(sys.platform != "win32", reason="measures Windows font metrics (malgun); needs recalibration on the Mac")
def test_PHOTO_04_real_contract_photo_reads_in_order_with_the_bullet():
    text = full_text(OcrEngine().recognize(cv2.imread(PHOTO)))
    lines = text.split("\n")
    assert lines[0].startswith("◆"), lines[0]
    order = [next(i for i, l in enumerate(lines) if l.startswith(f"{n}.")) for n in (1, 2, 3, 4, 5)]
    assert order == sorted(order), lines
    # blurry print read more clearly (the enlarged, sharpened pass)
    assert "건물" in text and "물티슈" in text, text


def test_PHOTO_05_a_tilted_photo_row_is_still_one_row():
    """The user's table photo leans ~2°: the right end of a row sits 16 px lower than its
    left end, more than the usual tolerance - the tilt is measured from the boxes themselves."""
    row = [("주택", (31, 75, 40, 24)), ("소재지", (73, 75, 61, 23)), ("서울특별시", (154, 76, 99, 26)),
           ("관악구", (255, 81, 60, 24)), ("봉천동", (319, 85, 60, 24)), ("867-4외", (378, 88, 78, 25)),
           ("1필지", (459, 92, 50, 22)), ("제11층 제 1102호", (513, 94, 149, 27))]
    nxt = [("주택", (41, 120, 40, 23)), ("유형", (83, 120, 41, 24)), ("아파트[", (153, 122, 72, 28)),
           ("연립주택[", (294, 128, 89, 29)), ("다세대주택[", (457, 134, 104, 29)), ("다가구주택[", (633, 141, 102, 27))]
    lines = ocr_row_lines(row + nxt)
    assert len(lines) == 2, lines
    assert lines[0].startswith("주택 소재지") and lines[0].endswith("1102호")
    assert lines[1].startswith("주택 유형") and "다가구주택[" in lines[1]
    # the same boxes as OCR lines: reading order and joining agree
    ol = [OcrLine(t, b, 0.9) for t, b in nxt + row]
    assert full_text(ol).split("\n")[0].endswith("1102호")


@real_ocr
def test_PHOTO_06_real_table_photo_rows_are_whole():
    lines = ocr_row_lines([(l.text, l.box) for l in OcrEngine().recognize(cv2.imread("tests/data/contract_photo_table.png"))])
    addr = next(l for l in lines if "소재지" in l)
    assert "1102호" in addr, lines
