"""도형PPT on a web form: labels stay where they are as separate text boxes, panels stay empty
behind them, input fields are boxes, radio buttons and check boxes are their own shapes, and
dropdown arrows / icon bits don't turn into text or arrows."""
from pathlib import Path

import cv2
import pytest

from capture_tool.core.ocr import OcrEngine
from capture_tool.core.shapes import recognize_layout

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


def layout(ocr, name):
    img = cv2.imread(str(DATA / name))
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    det = recognize_layout(img, lines, lambda crop: [(l.text, l.box) for l in ocr.recognize(crop)], 96)
    return img, lines, det


def texts(det):
    return [d.text for d in det if d.text]


def test_FORM_01_panels_do_not_swallow_their_labels(ocr):
    """Bug (v0.7.6): every label of a panel became one centred multi-line text in the panel."""
    _, lines, det = layout(ocr, "form_search_panel.png")
    assert all((d.text or "").count("\n") <= 1 for d in det), [d.text for d in det if d.text and "\n" in d.text]
    joined = " ".join(texts(det))
    for word in ("분류", "전자세금계산서", "조회기간", "작성일자", "공급자", "사업자등록번호", "총 합계금액", "공급가액", "세액", "품목명"):
        assert word in joined, word


def test_FORM_02_labels_keep_their_place(ocr):
    _, lines, det = layout(ocr, "form_search_panel.png")
    for word, (x, y) in (("분류", (35, 33)), ("조회기간", (600, 104)), ("총 합계금액", (63, 315))):
        d = next(d for d in det if d.text and word in d.text)
        cx, cy = d.x + d.w / 2, d.y + d.h / 2
        assert abs(cx - x) < 60 and abs(cy - y) < 15, (word, d)


def test_FORM_03_input_fields_are_boxes_not_two_lines(ocr):
    _, _, det = layout(ocr, "form_search_panel.png")
    fields = [d for d in det if d.kind in ("rect", "roundRect") and 22 <= d.h <= 45 and 60 <= d.w <= 260]
    assert len(fields) >= 8, [(d.kind, d.x, d.y, d.w, d.h) for d in det]
    flat = [d for d in det if d.kind == "line" and d.h <= 2 and 60 <= d.w <= 260]
    assert len(flat) <= 4, flat


def test_FORM_04_dropdown_arrows_and_symbols_are_not_text(ocr):
    _, _, det = layout(ocr, "form_search_panel.png")
    assert not [t for t in texts(det) if t.strip() in ("¸", "V", "v", "˅", "O")]


def test_FORM_05_icons_do_not_become_arrows(ocr):
    _, _, det = layout(ocr, "form_search_panel.png")
    short = [d for d in det if d.kind in ("arrow", "line") and max(d.w, d.h) < 40]
    assert not short, short


def test_FORM_06_label_sizes_are_consistent(ocr):
    _, _, det = layout(ocr, "form_search_panel.png")
    sizes = [d.font_size for d in det if d.text and d.kind == "text"]
    assert sizes and max(sizes) <= 14 and min(sizes) >= 9, sizes


def test_FORM_07_panels_are_behind_what_is_on_them(ocr):
    from capture_tool.core.shapes import to_drawing
    _, _, det = layout(ocr, "form_search_panel.png")
    shapes, _ = to_drawing(det)
    areas = [s.w * s.h for s in shapes if not s.text]
    assert areas == sorted(areas, reverse=True)                 # bigger empty shapes drawn first
    assert all(s.text for s in shapes[-3:])                     # text boxes on top


def test_FORM_08_radio_buttons_and_check_boxes(ocr):
    """Bug (v0.7.6): the radio row lost its check boxes and "(" ; the empty radio became text "O"."""
    _, _, det = layout(ocr, "form_radio_row.png")
    circles = [d for d in det if d.kind == "ellipse" and 12 <= d.w <= 26]
    boxes = [d for d in det if d.kind in ("rect", "roundRect") and 12 <= d.w <= 26 and 0.8 <= d.w / d.h <= 1.25]
    assert len(circles) == 2, [(d.kind, d.x, d.y, d.w, d.h) for d in det]
    assert len(boxes) == 2, [(d.kind, d.x, d.y, d.w, d.h) for d in det]
    filled = sorted(circles, key=lambda d: d.x)
    assert filled[0].fill and filled[0].fill.upper().startswith("#2")          # chosen radio: blue
    t = texts(det)
    assert "O" not in [x.strip() for x in t]
    assert sum("위수탁" in x for x in t) == 2 and any("전자세금계산서" in x for x in t)


def test_FORM_09_tables_on_a_screen_keep_their_cells(ocr):
    """User (v0.7.7): the tables came out as one box with loose headers - no cells, no header colour."""
    _, _, det = layout(ocr, "form_tax_tables.png")
    head1 = [d for d in det if d.kind == "rect" and 130 <= d.y <= 145 and 35 <= d.h <= 55 and d.w >= 60]
    head2 = [d for d in det if d.kind == "rect" and 350 <= d.y <= 362 and 35 <= d.h <= 55 and d.w >= 200]
    assert len(head1) >= 10, [(d.kind, d.x, d.y, d.w, d.h) for d in det if d.kind != "text"]
    assert len(head2) == 6, [(d.kind, d.x, d.y, d.w, d.h) for d in det if d.kind != "text"]
    assert all(d.fill and d.fill.upper() != "#FFFFFF" for d in head2)          # header colour kept
    assert all(d.text in ("은행명", "계좌번호") for d in head2)                 # each header in its cell
    body2 = [d for d in det if d.kind == "rect" and 400 <= d.y <= 450 and d.w >= 200 and 35 <= d.h <= 55]
    assert len(body2) >= 12


def test_FORM_10_buttons_keep_their_colour_and_no_box_inside(ocr):
    _, _, det = layout(ocr, "form_tax_tables.png")
    ok = next(d for d in det if d.text == "확인")
    one = next(d for d in det if d.text == "1")
    assert ok.kind != "text" and ok.fill.upper() == "#8E8E8E", ok
    assert one.kind != "text" and one.fill.upper() == "#8E8E8E", one
    assert not [d for d in det if d.kind == "text" and d.fill]                  # no coloured patches


def test_FORM_11_ring_icon_is_not_a_letter(ocr):
    _, _, det = layout(ocr, "form_tax_tables.png")
    title = next(d for d in det if d.text and "가상계좌 내역" in d.text)
    assert title.text == "가상계좌 내역", title.text
    assert [d for d in det if d.kind == "ellipse" and d.x < 30 and 320 <= d.y <= 345]
