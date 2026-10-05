"""Real Excel / PowerPoint (skipped when Office is missing): Excel screenshots -> table cells,
our table pasted into Excel, an AI-style table into PowerPoint, styled shapes round trip."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]


def _installed(exe: str) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"):
            return True
    except OSError:
        return False


def flow(*args, ok=lambda o: "RESULT" in o) -> str:
    from tests.conftest import run_on_desktop
    p = str(ROOT / "tests" / "office_flows.py")
    code = f"import sys; sys.argv = {['x', *args]!r}; sys.path.insert(0, {str(ROOT)!r}); " \
           f"exec(compile(open({p!r}, encoding='utf-8').read(), {p!r}, 'exec'), " \
           f"{{'__name__': '__main__', '__file__': {p!r}}})"
    return run_on_desktop(code, ok, timeout=240)


excel = pytest.mark.skipif(not _installed("excel.exe"), reason="Excel not installed")
ppt = pytest.mark.skipif(not _installed("POWERPNT.EXE"), reason="PowerPoint not installed")


@excel
@pytest.mark.parametrize("opts", ["plain", "nogrid", "header-fill", "bare", "headers", "bare headers",
                                  "header-fill headers"])
def test_OFFICE_01_excel_screenshot_becomes_the_same_cells(opts):
    good = lambda o: "RESULT cells_ok 30/30" in o            # noqa: E731
    out = flow("excel_table", opts, ok=good)
    assert good(out), out


@excel
def test_OFFICE_02_pasted_table_keeps_codes_and_never_runs_formulas():
    out = flow("excel_paste")
    assert "('007', 'str')" in out and "('=SUM(A1)', 'str')" in out and "'float'" in out, out
    heights = eval(out.split("HEIGHTS", 1)[1].split("]")[0].strip() + "]")     # long cells don't wrap
    assert max(heights) <= 20, out


@ppt
def test_OFFICE_03_ai_table_becomes_a_powerpoint_table():
    out = flow("ppt_table")
    assert "[['분기', '매출'], ['3분기', '1,250억'], ['4분기', '1,320억']]" in out, out


@ppt
def test_OFFICE_04_captured_shapes_keep_their_look_in_powerpoint():
    out = flow("ppt_shapes", ok=lambda o: "RESULT done" in o)
    shapes = [l for l in out.splitlines() if l.startswith("SHAPE")]
    want = ["SHAPE 1 #1F5FD1 #0B3A8C ('요청 접수', '#FFFFFF', 20.0, True)",
            "SHAPE 5 None #E8730C ('검토', '#E8730C', 18.0, False)",
            "SHAPE 9 #2E9E5B None ('승인', '#1A1A1A', 22.0, True)",
            "SHAPE 4 #F5C518 #333333 ('예산 확인', '#000000', 16.0, False)",
            "SHAPE 7 #D93025 None ()",
            "SHAPE 1 #F2F2F2 #7F7F7F ('보류/사유 기록', '#C00000', 14.0, False)",
            "SHAPE 1 None None ('업무 처리 흐름', '#404040', 28.0, True)"]
    for w in want:
        assert w in shapes, (w, out)


@ppt
def test_OFFICE_05_dark_table_into_powerpoint_styled_and_plain():
    styled = flow("ppt_dark_table", "1", ok=lambda o: "RESULT width" in o)
    assert "CELL (1, 1, '축', '#2F2D2B'" in styled and "CELL (2, 1, '전체 평균', '#1F1F1E'" in styled, styled
    assert "TITLE ['측정값(haiku 1회):']" in styled
    plain = flow("ppt_dark_table", "0", ok=lambda o: "RESULT width" in o)
    assert "'#2F2D2B'" not in plain and "CELL (2, 1, '전체 평균'" in plain, plain


@ppt
def test_OFFICE_06_screen_tables_go_in_as_real_tables(tmp_path):
    """도형PPT straight into PowerPoint: the screen's ruled tables are real, editable tables placed
    where they were (left edge with the other shapes), icons come in as pictures."""
    src = str(ROOT / "tests" / "data" / "form_tax_tables.png")
    out = flow("ppt_form_send", src, str(tmp_path / "slide.png"), ok=lambda o: "RESULT done" in o)
    tables = [l for l in out.splitlines() if l.startswith("TABLE")]
    assert len(tables) == 2, out
    assert "'과세년월'" in out and "'은행명'" in out
    lefts = {int(l.split(",")[2]) for l in tables}
    left_all = int(out.split("LEFTMOST (")[1].split(",")[1])
    assert all(abs(x - left_all) <= 3 for x in lefts), out


@ppt
def test_OFFICE_11_diagram_cards_are_few_shapes_in_powerpoint(tmp_path):
    """BUG-099: a card is one shape holding its text, the dashed box one shape - not 120 pieces."""
    src = str(ROOT / "tests" / "data" / "diagram_cards.png")
    out = flow("ppt_form_send", src, str(tmp_path / "slide.png"), ok=lambda o: "RESULT done" in o)
    assert 10 <= int(out.split("SHAPES ")[1].split()[0]) <= 60, out


@ppt
def test_OFFICE_07_terminal_table_into_powerpoint(tmp_path):
    """Bug (v0.7.9): a table drawn with line characters lost D1-D3 and its wrapped lines."""
    src = str(ROOT / "tests" / "data" / "terminal_box_table.png")
    out = flow("ppt_box_table", src, str(tmp_path / "slide.png"), "1", ok=lambda o: "RESULT done" in o)
    assert "SIZE (6, 3)" in out, out
    for want in ("'D1'", "'D2'", "'D3'", "'D4'", "'D5'", "낡음", "승격 안 됨", "아무 모름"):
        assert want in out, (want, out)


word = pytest.mark.skipif(not _installed("WINWORD.EXE"), reason="Word not installed")


@word
def test_OFFICE_08_terminal_table_into_word():
    """User (v0.8.1): 표 → Word like Excel / PowerPoint. A separate Word instance, closed unsaved."""
    src = str(ROOT / "tests" / "data" / "terminal_box_table.png")
    out = flow("word_table", src, "1", ok=lambda o: "RESULT done" in o)
    assert "TABLES 1" in out and "SIZE (6, 3)" in out, out
    cols = eval(out.split("COLS ")[1].split(" SEL")[0])
    page = int(out.split("PAGE ")[1].split(" ")[0])
    assert sum(cols) <= page + 2 and min(cols) >= 39, out
    assert "아무 모름" in out and "commit ↔ Jira" in out


@pytest.mark.skipif(not _installed("EXCEL.EXE"), reason="Excel not installed")
def test_OFFICE_09_coloured_words_keep_their_colour_in_excel():
    """User (v0.8.1): '"관행 "으로만' (lavender) came out in the table's one text colour."""
    src = str(ROOT / "tests" / "data" / "terminal_small_table.png")
    out = flow("excel_box_table", src, ok=lambda o: "RESULT done" in o)
    row = [l for l in out.splitlines() if l.startswith("CELL 3")][0]
    assert "관행" in row and "0xf9b9b1" in row, out


@ppt
def test_OFFICE_10_coloured_words_keep_their_colour_in_powerpoint(tmp_path):
    src = str(ROOT / "tests" / "data" / "terminal_small_table.png")
    out = flow("ppt_box_table", src, str(tmp_path / "s.png"), "1", ok=lambda o: "RESULT done" in o)
    assert "SIZE (5, 1)" in out and "'0xf9b9b1'" in out.split("COLORS")[1], out


# --- text with its look (v0.8.11) -------------------------------------------------------------------

STYLED = str(ROOT / "tests" / "data" / "styled_code_dark.png")


def _near(hex_, want, tol=60):
    return max(abs(int(hex_[i:i + 2], 16) - w) for i, w in zip((1, 3, 5), want)) <= tol


@pytest.mark.skipif(not _installed("EXCEL.EXE"), reason="Excel not installed")
def test_OFFICE_12_styled_text_into_excel_one_line_per_row():
    out = flow("styled_excel", STYLED, ok=lambda o: "RESULT done" in o)
    used = out.split("USED ")[1].split()
    rows = [l for l in out.splitlines() if l.startswith("ROW ")]
    assert used[0] == used[3] and used[1] == "1" and len(rows) == int(used[0]), out      # a row per line, one column
    assert all("FILL #1F1F1E" in r and "FORMULA False" in r for r in rows), out          # the page colour; nothing runs
    assert all("FONT Consolas" in r for r in rows), out
    kw = [r.split("FROM ")[1].split()[0] for r in rows if "from pathlib" in r or "from PIL" in r]
    assert len(kw) == 2 and all(_near(k, (249, 38, 114)) for k in kw), out


@word
def test_OFFICE_13_styled_text_into_word_keeps_colours_and_page_colour():
    out = flow("styled_word", STYLED, ok=lambda o: "RESULT done" in o)
    assert "TABLES 1" in out and "FILL #1F1F1E" in out, out
    words = eval(out.split("WORDS ")[1].splitlines()[0])
    assert _near(words["from"][0], (249, 38, 114)) and _near(words["import"][0], (249, 38, 114)), words
    assert _near(words["pathlib"][0], (248, 248, 242)) and _near(words["outlines"][0], (230, 219, 116)), words
    assert all(v[1] == "Consolas" for v in words.values()), words


@ppt
def test_OFFICE_14_styled_text_into_powerpoint_is_one_filled_text_box(tmp_path):
    out = flow("styled_ppt", STYLED, str(tmp_path / "slide.png"), ok=lambda o: "RESULT done" in o)
    box = eval(out.split("BOX ")[1].splitlines()[0])
    lines = int(out.split("LINES ")[1].split()[0])
    assert box[0] == "#1F1F1E" and box[1] is True and box[2] == lines and box[3] == "Consolas", out
    assert box[4] <= box[6], out                                                          # inside the slide
    words = eval(out.split("WORDS ")[1].splitlines()[0])
    assert _near(words["from"], (249, 38, 114)) and _near(words["pathlib"], (248, 248, 242)), words
    assert _near(words["outlines"], (230, 219, 116)), words
