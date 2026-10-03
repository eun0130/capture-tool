"""A table in a capture (light or dark page, with or without ruling lines) goes to PowerPoint
as a real table, with or without its look; diagrams and ordinary text are not tables."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from capture_tool.core.table_capture import find_table
from tests.test_app import make  # noqa: F401 (fixture)

DATA = Path(__file__).parent / "data"
# OCR lines (text, box, score) of tests/data/dark_table.png, recorded from the real engine
DARK_LINES = [("측정값(haiku 1회):", (42, 29, 196, 31), 0.96), ("축", (50, 124, 36, 37), 0.93),
              ("값", (455, 127, 30, 32), 0.98), ("요구", (855, 125, 55, 34), 1.0),
              ("전체 평균", (52, 182, 107, 34), 0.98), ("4.05", (453, 186, 52, 28), 1.0),
              ("≥ 4.0", (855, 185, 64, 32), 0.97), ("자연스러움", (52, 240, 121, 33), 1.0),
              ("3.65", (453, 242, 53, 31), 1.0), ("≥ 3.5", (855, 241, 64, 33), 0.9),
              ("레벨 적합성", (53, 296, 127, 32), 0.92), ("4.25", (453, 298, 53, 30), 1.0),
              ("≥ 3.5", (855, 297, 64, 32), 0.91), ("교정 유용성", (53, 353, 128, 32), 0.99),
              ("3.95", (453, 355, 53, 30), 1.0), ("≥ 3.5", (855, 354, 63, 32), 0.91),
              ("시나리오 준수", (53, 409, 151, 33), 0.99), ("4.35", (453, 411, 53, 31), 1.0),
              ("≥3.5", (854, 409, 66, 35), 0.98)]
DPI = 144


def near(h1, h2, tol=24):
    return max(abs(int(h1[i:i + 2], 16) - int(h2[i:i + 2], 16)) for i in (1, 3, 5)) <= tol


def light(h):
    return min(int(h[i:i + 2], 16) for i in (1, 3, 5)) >= 180


def test_TCAP_01_dark_table_screenshot_becomes_a_table():
    """Bug (v0.6.4): a dark-page table sent by 도형PPT became stacked white text boxes,
    invisible on a white slide."""
    img = cv2.imread(str(DATA / "dark_table.png"))
    t = find_table(img, DARK_LINES, [], DPI)
    assert t is not None
    assert t.rows == [["축", "값", "요구"], ["전체 평균", "4.05", "≥ 4.0"], ["자연스러움", "3.65", "≥ 3.5"],
                      ["레벨 적합성", "4.25", "≥ 3.5"], ["교정 유용성", "3.95", "≥ 3.5"], ["시나리오 준수", "4.35", "≥3.5"]]
    assert [text for text, _ in t.outside] == ["측정값(haiku 1회):"]      # the title stays as text
    st = t.style
    assert near(st.header_fill, "#2F2D2B") and near(st.body_fill, "#1F1F1E")
    assert light(st.header_text) and light(st.body_text)
    assert st.font_size in (12, 14) and st.header_bold
    x, y, w, h = t.box
    assert x < 50 and y < 124 and x + w > 920 and y + h > 440
    assert len(t.col_widths) == 3 and t.col_widths[0] < t.col_widths[2] + 400


def grid_table(rows=5, cols=3, cw=200, rh=40, x0=20, y0=20, line=(212, 212, 212), header=None):
    img = np.full((y0 * 2 + rows * rh + 1, x0 * 2 + cols * cw + 1, 3), 255, np.uint8)
    if header:
        img[y0:y0 + rh, x0:x0 + cols * cw] = header
    for r in range(rows + 1):
        img[y0 + r * rh, x0:x0 + cols * cw + 1] = line
    for c in range(cols + 1):
        img[y0:y0 + rows * rh + 1, x0 + c * cw] = line
    lines = [(f"r{r}c{c}", (x0 + c * cw + 10, y0 + r * rh + 10, 60, 20), 0.99) for r in range(rows) for c in range(cols)]
    for r in range(rows):
        for c in range(cols):
            cv2.putText(img, f"r{r}c{c}", (x0 + c * cw + 12, y0 + r * rh + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255) if header and r == 0 else (30, 30, 30), 2)
    return img, lines


def test_TCAP_02_light_table_with_lines():
    img, lines = grid_table(header=(160, 90, 30))
    t = find_table(img, lines, [], 96)
    assert t is not None and len(t.rows) == 5 and t.rows[0] == ["r0c0", "r0c1", "r0c2"] and t.outside == []
    assert near(t.style.header_fill, "#1E5AA0") and near(t.style.body_fill, "#FFFFFF")
    assert near(t.style.border, "#D4D4D4", 40)


def test_TCAP_03_diagram_with_shapes_is_not_a_table():
    from capture_tool.core.shapes import Detected
    img, lines = grid_table()
    shapes = [Detected("rect", 30, 30, 300, 150, fill="#FFFFFF", stroke="#000000")]
    assert find_table(img, lines, shapes, 96) is None


@pytest.mark.parametrize("lines", [
    [],
    [("첫 문단의 긴 문장입니다.", (20, 20, 600, 24), 0.99), ("둘째 줄입니다.", (20, 60, 300, 24), 0.99),
     ("셋째 줄.", (20, 100, 120, 24), 0.99)],                                    # a paragraph
    [("이름", (20, 20, 60, 24), 0.99), ("나이", (300, 20, 60, 24), 0.99),
     ("김", (20, 60, 30, 24), 0.99), ("30", (300, 60, 30, 24), 0.99)],          # only two rows
    [("메뉴", (20, 20, 60, 24), 0.99), ("설정", (300, 20, 60, 24), 0.99),
     ("본문 단락이 이어집니다", (20, 300, 400, 24), 0.99), ("끝", (20, 900, 30, 24), 0.99),
     ("x", (600, 905, 10, 24), 0.99)],                                           # scattered, irregular
])
def test_TCAP_04_ordinary_text_is_not_a_table(lines):
    img = np.full((1000, 800, 3), 255, np.uint8)
    assert find_table(img, lines, [], 96) is None


def test_TCAP_05_mostly_empty_grid_is_not_a_table():
    lines = [("a", (20, 20, 20, 20), 0.99), ("b", (300, 20, 20, 20), 0.99), ("c", (20, 60, 20, 20), 0.99),
             ("d", (20, 100, 20, 20), 0.99), ("e", (20, 140, 20, 20), 0.99)]
    img = np.full((300, 500, 3), 255, np.uint8)
    assert find_table(img, lines, [], 96) is None


def test_TCAP_06_huge_input_is_bounded():
    lines = [(f"{r}-{c}", (20 + c * 90, 20 + r * 30, 50, 20), 0.99) for r in range(300) for c in range(30)]
    img = np.full((9100, 2800, 3), 255, np.uint8)
    t = find_table(img, lines, [], 96)
    assert t is None or (len(t.rows) <= 200 and len(t.rows[0]) <= 20)


# --- in the app: 도형 / PPT 도형 on a table ------------------------------------------------------
def _dark_controller(make, keep_style=True):
    from capture_tool.core.ocr import OcrLine
    from tests.test_app import FakeOcr, FakePpt
    img = cv2.imread(str(DATA / "dark_table.png"))
    c = make(ocr=FakeOcr([OcrLine(t, b, s) for t, b, s in DARK_LINES]))
    c.settings.keep_style = keep_style
    c.powerpoint = FakePpt()
    c._run_recognition_on(img, "ppt", dpi=DPI)
    return c


def test_TCAP_07_ppt_shapes_on_a_table_sends_a_styled_powerpoint_table(make):
    from capture_tool.platform.powerpoint import TableItem
    c = _dark_controller(make)
    item = c.powerpoint.items[-1]
    assert isinstance(item, TableItem) and len(item.rows) == 6 and item.title == "측정값(haiku 1회):"
    assert item.style is not None and light(item.style.body_text) and len(item.col_widths) == 3
    assert any("표" in m for m in c.messages)


def test_TCAP_08_without_style_the_table_is_plain(make):
    c = _dark_controller(make, keep_style=False)
    item = c.powerpoint.items[-1]
    assert item.style is None and item.title == "측정값(haiku 1회):"


def test_TCAP_09_copied_table_html_carries_style_only_when_kept():
    from capture_tool.core.clipboard_payload import HTML, UNICODE, table_payload
    from capture_tool.core.table_capture import TableStyle
    st = TableStyle("#2F2D2B", "#1F1F1E", "#FFFFFF", "#EEEEEE", "#2C2A27", True, 14)
    rows = [["축", "값"], ["평균", "4.05"]]
    p = table_payload(rows, style=st, title="측정값")
    html = p[HTML].decode("utf-8")
    assert "background:#2F2D2B" in html and "color:#EEEEEE" in html and "font-weight:bold" in html
    assert "측정값" in html and p[UNICODE].startswith("측정값\r\n축\t값")
    plain = table_payload(rows)[HTML].decode("utf-8")
    assert "background:" not in plain and "<table" in plain


# --- text mode: a "표로 복사" button when the text is laid out as a table --------------------------
def _text_mode(make, img, lines):
    from capture_tool.core.ocr import OcrLine
    from tests.test_app import FakeOcr, drag
    ocr_lines = [OcrLine(t, b, s) for t, b, s in lines]
    c = make(ocr=FakeOcr(ocr_lines))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    c._text_ctx = (ov, img)
    c.active_overlay = ov
    c._acted = True
    c._on_text_ready((ocr_lines, None))
    return c, ov


def test_TCAP_10_text_mode_offers_table_copy_for_a_table(make):
    from capture_tool.core.clipboard_payload import UNICODE
    c, ov = _text_mode(make, cv2.imread(str(DATA / "dark_table.png")), DARK_LINES)
    assert not ov.ocr_bar.buttons["table"].isHidden()
    ov.ocr_bar.trigger("table")
    assert c.clipboard.last[UNICODE].split("\r\n")[1] == "전체 평균\t4.05\t≥ 4.0"
    assert any("표 6행×3열" in m for m in c.messages)


def test_TCAP_11_text_mode_hides_table_copy_for_plain_text(make):
    lines = [("첫 문단의 긴 문장입니다.", (20, 20, 600, 24), 0.99), ("둘째 줄입니다.", (20, 60, 300, 24), 0.99)]
    c, ov = _text_mode(make, np.full((200, 700, 3), 255, np.uint8), lines)
    assert ov.ocr_bar.buttons["table"].isHidden()
    ov.ocr_bar.trigger("table")
    assert any("표 모양" in m for m in c.messages)
