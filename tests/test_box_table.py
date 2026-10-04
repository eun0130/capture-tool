"""Tables drawn with line characters (a terminal, a console, Markdown-ish output): rows between the
horizontal rules, columns at the header's bars; text the terminal wrapped onto the next line
belongs to the cell it overflowed from, and the bar characters never end up in the text."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from capture_tool.core.box_table import _join, find_box_table
from capture_tool.core.ocr import OcrEngine
from tests.test_app import make  # noqa: F401 (fixture)

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def ocr():
    return OcrEngine()


@pytest.fixture(scope="module")
def terminal(ocr):
    img = cv2.imread(str(DATA / "terminal_box_table.png"))
    return find_box_table(img, ocr.read_words, 96)


def flat(s):
    return s.replace(" ", "")


def test_BOX_01_all_rows_and_columns(terminal):
    """Bug (v0.7.9): only D4-D5 came out, the rest was lost."""
    t = terminal
    assert t is not None
    assert len(t.rows) == 6 and all(len(r) == 3 for r in t.rows), t.rows
    assert [flat(r[0]) for r in t.rows] == ["#", "D1", "D2", "D3", "D4", "D5"]
    assert [flat(c) for c in t.rows[0]] == ["#", "단절", "증상"]


def test_BOX_02_cells_split_at_the_bars_and_bars_removed(terminal):
    rows = {flat(r[0]): r for r in terminal.rows}
    assert flat(rows["D2"][1]).startswith("commit") and "관행" not in rows["D2"][1]
    assert flat(rows["D2"][2]).startswith('"관행"') or flat(rows["D2"][2]).startswith("“관행")
    for r in terminal.rows:
        for c in r:
            assert not any(ch in c for ch in "│|ㅣ┃"), c


def test_BOX_03_wrapped_text_goes_back_to_its_cell(terminal):
    rows = {flat(r[0]): r for r in terminal.rows}
    assert flat(rows["D1"][2]).endswith("만존재,항상낡음") or flat(rows["D1"][2]).endswith("만존재·항상낡음") \
        or "항상낡음" in flat(rows["D1"][2]), rows["D1"]
    assert "Excel" in rows["D1"][2] and "만존재" not in flat(rows["D1"][1])
    assert flat(rows["D2"][1]).endswith("안됨"), rows["D2"]
    # the capture cuts "불" in half at its left edge: the wrapped "?가" must still follow "역추적"
    d2 = flat(rows["D2"][2])
    assert "역추적" in d2 and d2.endswith("가"), rows["D2"]
    assert flat(rows["D4"][2]).endswith("아무모름"), rows["D4"]
    assert "분석이산출물로" in flat(rows["D5"][2]) and flat(rows["D5"][2]).endswith("승격안됨"), rows["D5"]
    assert flat(rows["D5"][1]) == "CI가빌드만함", rows["D5"]


def test_BOX_04_letter_spacing_of_a_monospace_font(terminal):
    rows = {flat(r[0]): r for r in terminal.rows}
    assert rows["D1"][1] == "REQ ID 체계 없음", rows["D1"]
    assert rows["D3"][1] == "증거를 사람이 만듦", rows["D3"]


def test_BOX_05_dark_terminal_look_kept(terminal):
    st = terminal.style
    assert st is not None
    lum = lambda h: sum(int(h[i:i + 2], 16) for i in (1, 3, 5)) / 3     # noqa: E731
    assert lum(st.body_fill) < 80 and lum(st.body_text) > 170
    assert 12 <= st.font_size <= 15, st.font_size                       # the letters are ~17 px tall
    assert len(terminal.col_widths) == 3 and terminal.col_widths[2] > terminal.col_widths[1] > terminal.col_widths[0]


def test_BOX_06_not_a_box_table(ocr):
    img = np.full((200, 600, 3), 255, np.uint8)
    cv2.putText(img, "just some text", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    assert find_box_table(img, ocr.read_words, 96) is None
    assert find_box_table(None, ocr.read_words, 96) is None


def test_BOX_07_spacing_from_syllable_positions():
    w = lambda t, x, wd=14: (t, (x, 0, x + wd, 20))     # noqa: E731
    assert _join([w("체", 0), w("계", 34), w("없", 82), w("음", 121)], 34) == "체계 없음"
    assert _join([w("REQ", 0, 35), w("ID", 48, 20), w("체", 87)], 34) == "REQ ID 체"
    assert _join([w("│", 0, 3), w("가", 20)], 34) == "가"
    assert _join([], 34) == ""


def test_BOX_08_remaining_details(terminal):
    """User (v0.8.0): "↔" dropped, a space before the closing quote, white instead of grey rules."""
    rows = {flat(r[0]): r for r in terminal.rows}
    assert rows["D2"][1] == "commit ↔ Jira 키 강제 안 됨", rows["D2"]
    assert rows["D2"][2].startswith('"관행"으로만 존재'), rows["D2"]
    assert "URL. branch" in rows["D3"][2]
    lum = sum(int(terminal.style.border[i:i + 2], 16) for i in (1, 3, 5)) / 3
    assert 90 < lum < 200, terminal.style.border                       # looks grey, as on screen


def test_BOX_09_letters_cut_by_the_capture_edge_are_reported(terminal):
    assert terminal.cut_edge                                            # "불" is cut in half at the left


def test_BOX_10_cut_note_reaches_the_person(make):
    from capture_tool.core.table_capture import CapturedTable
    c = make()
    t = CapturedTable([["a", "b"], ["c", "d"]], (0, 0, 10, 10), cut_edge=True)
    c._finish_table(t, send=False)
    assert "잘린 글자" in c.messages[-1]
    t2 = CapturedTable([["a", "b"], ["c", "d"]], (0, 0, 10, 10))
    c._finish_table(t2, send=False)
    assert "잘린 글자" not in c.messages[-1]
