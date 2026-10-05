"""Text of a capture copied WITH its look: colours, bold, background, indentation, monospace or
not, symbols - so pasting into Excel / PowerPoint / Word / a web editor (Confluence) gives the
same-looking text, as text. Notepad still gets plain text. Drawn pictures in several fonts, sizes
and colours are checked besides the user's capture: the rules must not depend on one picture."""
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from capture_tool.core.clipboard_payload import HTML, UNICODE
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.styled_text import Run, StyledText, read_styled, styled_html, styled_payload, styled_plain

DATA = Path(__file__).parent / "data"
FONTS = Path("C:/Windows/Fonts")
DARK, LIGHT = (30, 30, 30), (255, 255, 255)
WHITE, BLACK = (235, 235, 235), (25, 25, 25)
PINK, YELLOW, GREEN, BLUE, RED = (249, 38, 114), (230, 219, 116), (80, 200, 120), (60, 120, 230), (220, 40, 40)


@pytest.fixture(scope="module")
def engine():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def font(names, size):
    for n in names if isinstance(names, (tuple, list)) else (names,):
        p = FONTS / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    pytest.skip(f"font missing: {names}")


MONO, MONO_BOLD = ("consola.ttf", "cour.ttf"), ("consolab.ttf", "courbd.ttf")
SANS, SANS_BOLD = ("malgun.ttf",), ("malgunbd.ttf",)


def draw(rows, bg, base_font, pad=20, gap=8, size=None):
    """rows: list of rows; a row is a list of (text, rgb[, font[, highlight rgb]]) pieces drawn one
    after the other (spaces inside the text count). Returns a BGR picture."""
    f0 = base_font
    lh = f0.getbbox("Agj가")[3] + gap
    width = 0
    for row in rows:
        width = max(width, sum(int((p[2] if len(p) > 2 and p[2] else f0).getlength(p[0])) for p in row))
    im = Image.new("RGB", size or (width + 2 * pad, lh * len(rows) + 2 * pad), bg)
    d = ImageDraw.Draw(im)
    for i, row in enumerate(rows):
        x = pad
        for p in row:
            f = p[2] if len(p) > 2 and p[2] else f0
            w = f.getlength(p[0])
            if len(p) > 3 and p[3]:
                d.rectangle([x - 1, pad + i * lh - 1, x + w + 1, pad + (i + 1) * lh - gap + 3], fill=p[3])
            d.text((x, pad + i * lh), p[0], font=f, fill=p[1])
            x += w
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def styled(engine, img):
    return read_styled(img, engine.recognize, engine.read_words, 96)


def rgb(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def near(hex_, want, tol=60):
    return hex_ is not None and max(abs(a - b) for a, b in zip(rgb(hex_), want)) <= tol


def color_of(st: StyledText, word: str):
    """Colour of the run(s) holding `word` (the first place it appears)."""
    for line in st.lines:
        text = "".join(r.text for r in line)
        i = text.find(word)
        if i < 0:
            continue
        pos, found = 0, []
        for r in line:
            a, b = pos, pos + len(r.text)
            if a < i + len(word) and b > i and r.text[max(0, i - a):i + len(word) - a].strip():
                found.append(r)
            pos = b
        assert found, word
        return found
    raise AssertionError(f"{word!r} not in {[''.join(r.text for r in l) for l in st.lines]}")


def text_lines(st):
    return ["".join(r.text for r in l) for l in st.lines]


# --- the user's capture ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def user(engine):
    return styled(engine, cv2.imread(str(DATA / "styled_code_dark.png")))


def test_ST_01_users_capture_lines_are_whole_lines(user):
    flat = [" ".join(t.split()) for t in text_lines(user)]
    for want in ["5 from pathlib import Path", "7 import cv2", "8 import numpy as np", "9 import pytest",
                 "10 from PIL import Image, ImageDraw, ImageFont"]:
        assert want in flat, (want, flat)
    assert any("every line became its own text box on top of the card" in t for t in flat), flat


def test_ST_02_users_capture_colours_and_background(user):
    assert near(user.bg, (12, 12, 12), 40) and near(user.fg, (235, 235, 235), 70), (user.bg, user.fg)
    assert all(near(r.color, PINK, 70) for r in color_of(user, "from")), color_of(user, "from")
    assert all(near(r.color, PINK, 70) for r in color_of(user, "import")), color_of(user, "import")
    assert all(near(r.color, YELLOW, 70) for r in color_of(user, "outlines were pasted")), color_of(user, "outlines")
    assert all(near(r.color, (235, 235, 235), 70) for r in color_of(user, "pathlib")), color_of(user, "pathlib")
    assert user.mono


def test_ST_03_users_capture_indentation(user):
    lines = text_lines(user)
    top = next(t for t in lines if "Write(" in t)
    wrote = next(t for t in lines if "Wrote 166" in t)
    code = next(t for t in lines if "from pathlib" in t)
    lead = lambda t: len(t) - len(t.lstrip(" "))  # noqa: E731
    assert lead(wrote) > lead(top) and lead(code) > lead(wrote), (top, wrote, code)


# --- drawn: code on a dark page ----------------------------------------------------------------------

CODE = [
    [("def ", PINK), ("total", GREEN), ("(items):", WHITE)],
    [("    for ", PINK), ("item ", WHITE), ("in ", PINK), ("items:", WHITE)],
    [("        price = item.cost", WHITE)],
    [],
    [("    return ", PINK), ("price  ", WHITE), ("# sum of all", YELLOW)],
]


@pytest.mark.parametrize("size", [16, 20, 26])
def test_ST_04_code_keeps_colours_indent_and_blank_line(engine, size):
    st = styled(engine, draw(CODE, DARK, font(MONO, size)))
    lines = text_lines(st)
    assert [" ".join(t.split()) for t in lines] == ["def total(items):", "for item in items:", "price = item.cost", "",
                                                    "return price # sum of all"], lines
    assert st.mono and near(st.bg, DARK, 25)
    assert [len(t) - len(t.lstrip(" ")) for t in lines] == [0, 4, 8, 0, 4], lines
    assert all(near(r.color, PINK) for r in color_of(st, "def")) and all(near(r.color, PINK) for r in color_of(st, "return"))
    assert all(near(r.color, GREEN) for r in color_of(st, "total"))
    assert all(near(r.color, YELLOW) for r in color_of(st, "sum of all"))
    assert all(near(r.color, WHITE) for r in color_of(st, "items:"))
    assert abs(st.size - size * 0.75) <= 0.2 * size * 0.75 + 1, st.size


def test_ST_05_column_gaps_inside_a_line_are_kept(engine):
    st = styled(engine, draw([[("name      size", WHITE)], [("alpha     120", WHITE)], [("be        7", WHITE)]],
                             DARK, font(MONO, 20)))
    lines = text_lines(st)
    assert lines[0].index("size") == lines[1].index("120") == lines[2].index("7"), lines


# --- drawn: a document on a light page -----------------------------------------------------------------

def test_ST_06_korean_document_colour_bold_highlight(engine):
    f, fb = font(SANS, 20), font(SANS_BOLD, 20)
    rows = [[("회의 결과 요약", BLACK, fb)],
            [("다음 주 수요일까지 ", BLACK), ("견적서를 보낸다", RED)],
            [("담당자는 ", BLACK), ("김대리", BLUE), (" 로 한다", BLACK)],
            [("중요: ", BLACK), ("금액 확인", BLACK, None, (255, 235, 59))]]
    st = styled(engine, draw(rows, LIGHT, f))
    lines = [" ".join(t.split()) for t in text_lines(st)]
    assert lines == ["회의 결과 요약", "다음 주 수요일까지 견적서를 보낸다", "담당자는 김대리 로 한다", "중요: 금액 확인"], lines
    assert not st.mono and near(st.bg, LIGHT, 20) and near(st.fg, BLACK, 50)
    assert all(near(r.color, RED) for r in color_of(st, "견적서를")) and all(near(r.color, BLUE) for r in color_of(st, "김대리"))
    assert all(near(r.color, BLACK, 70) for r in color_of(st, "수요일까지"))
    assert all(r.bold for r in color_of(st, "회의 결과")) and not any(r.bold for r in color_of(st, "수요일까지"))
    marked = color_of(st, "금액")
    assert all(near(r.bg, (255, 235, 59), 50) for r in marked), marked
    assert all(r.bg is None for r in color_of(st, "담당자는"))


def test_ST_07_same_colour_line_is_one_run(engine):
    st = styled(engine, draw([[("모든 글자가 같은 색인 한 줄입니다", BLACK)]], LIGHT, font(SANS, 20)))
    assert len(st.lines) == 1 and len(st.lines[0]) == 1, st.lines


def test_ST_08_symbols_come_back_as_characters(engine):
    f = font(MONO, 22)
    sym = font(("seguisym.ttf", "segoeui.ttf"), 22)
    img = draw([[("● ", GREEN, sym), ("Write(file.py)", WHITE)], [("  └ ", (150, 150, 150), f), ("Wrote 12 lines", WHITE)]],
               DARK, f)
    st = styled(engine, img)
    lines = text_lines(st)
    assert lines[0].lstrip().startswith("●") and "Write(file.py)" in lines[0], lines
    assert "└" in lines[1] and lines[1].index("└") < lines[1].index("Wrote"), lines
    assert all(near(r.color, GREEN, 70) for r in color_of(st, "●"))


# --- odd inputs --------------------------------------------------------------------------------------

def test_ST_09_nothing_to_read(engine):
    assert read_styled(np.full((80, 200, 3), 255, np.uint8), engine.recognize, engine.read_words, 96) is None
    assert read_styled(np.zeros((0, 0, 3), np.uint8), engine.recognize, engine.read_words, 96) is None
    assert read_styled(None, engine.recognize, engine.read_words, 96) is None
    assert read_styled(np.full((3, 3, 3), 255, np.uint8), engine.recognize, engine.read_words, 96) is None


def test_ST_10_grey_picture_and_one_word(engine):
    img = cv2.cvtColor(draw([[("Hello", BLACK)]], LIGHT, font(SANS, 24)), cv2.COLOR_BGR2GRAY)
    st = styled(engine, img)
    assert text_lines(st) == ["Hello"] and near(st.lines[0][0].color, BLACK, 60)


def test_ST_11_reader_without_word_boxes_still_gives_text(engine):
    img = draw([[("plain ", BLACK), ("red", RED)]], LIGHT, font(SANS, 24))
    st = read_styled(img, engine.recognize, lambda im: [], 96)
    assert [" ".join(t.split()) for t in text_lines(st)] == ["plain red"]
    st2 = read_styled(img, engine.recognize, None, 96)
    assert [" ".join(t.split()) for t in text_lines(st2)] == ["plain red"]


def test_ST_12_reader_error_is_not_fatal(engine):
    def boom(im):
        raise RuntimeError("no word boxes")
    img = draw([[("still works", BLACK)]], LIGHT, font(SANS, 24))
    assert text_lines(read_styled(img, engine.recognize, boom, 96)) == ["still works"]


# --- what goes on the clipboard -----------------------------------------------------------------------

def sample():
    return StyledText(lines=[[Run("def ", "#F92672", bold=True), Run("f(a<b & c):", "#EEEEEE")],
                             [Run("    return ", "#F92672"), Run("x  y", "#EEEEEE", bg="#444400")],
                             [],
                             [Run("끝", "#EEEEEE")]],
                      bg="#1E1E1E", fg="#EEEEEE", mono=True, size=12.0)


def test_ST_13_plain_text_is_the_text_with_its_indent():
    assert styled_plain(sample()) == "def f(a<b & c):\r\n    return x  y\r\n\r\n끝"


def test_ST_14_html_carries_the_look_safely():
    h = styled_html(sample())
    assert h.count("<td") == 1 and "background-color:#1E1E1E" in h and "bgcolor=\"#1E1E1E\"" in h   # one block, its page colour
    assert "color:#F92672" in h and "color:#EEEEEE" in h and "background-color:#444400" in h
    assert "<b>" in h or "font-weight:bold" in h
    assert "a&lt;b &amp; c" in h and "<b " not in h.replace("<b>", "")            # escaped, no stray tags
    assert h.count("<br") == 3                                                      # 4 lines, the empty one too
    assert "&nbsp;&nbsp;&nbsp;&nbsp;" in h and "x&nbsp; y" in h                    # indent and double spaces survive
    assert "Consolas" in h and "font-size:12pt" in h
    assert "<script" not in h.lower() and "javascript:" not in h.lower()


def test_ST_15_html_without_background_and_proportional_font():
    st = sample()
    st.mono = False
    h = styled_html(st, keep_bg=False)
    assert "#1E1E1E" not in h and "Consolas" not in h and "Malgun Gothic" in h
    assert "color:#F92672" in h                                                    # (the user's own page colour shows through)


def test_ST_16_payload_has_plain_text_and_html():
    p = styled_payload(sample())
    assert p[UNICODE] == styled_plain(sample())
    raw = p[HTML]
    assert raw.startswith(b"Version:") and b"StartFragment" in raw and "끝".encode("utf-8") in raw


def test_ST_17_text_that_looks_like_markup_or_a_formula_is_only_text():
    st = StyledText(lines=[[Run("=SUM(A1:A9)", "#000000")], [Run("<img src=x onerror=alert(1)>", "#000000")],
                           [Run("'; DROP TABLE x;--", "#000000")]], bg="#FFFFFF", fg="#000000", mono=False, size=11)
    h = styled_html(st)
    assert "<img" not in h and "&lt;img" in h
    assert 'mso-number-format:"\\@"' in h                                           # Excel keeps "=SUM(" as text


def test_ST_18_very_long_and_many_lines_stay_bounded():
    st = StyledText(lines=[[Run("x" * 5000, "#000000")]] * 400, bg="#FFFFFF", fg="#000000", mono=True, size=10)
    p = styled_payload(st)
    assert len(p[HTML]) < 6_000_000 and p[UNICODE].count("\r\n") == 399


def test_ST_19_runs_of_one_look_are_merged_and_empty_ones_dropped():
    from capture_tool.core.styled_text import tidy
    line = tidy([Run("ab", "#FF0000"), Run("", "#00FF00"), Run("cd", "#FE0101"), Run(" ", "#123456"), Run("ef", "#0000FF")])
    assert [(r.text, r.color) for r in line] == [("abcd ", "#FF0000"), ("ef", "#0000FF")]


def test_ST_20_hiding_personal_data_keeps_the_colours():
    from capture_tool.core.styled_text import redact
    st = StyledText(lines=[[Run("연락처 ", "#000000"), Run("010-1234-5678", "#FF0000")]], bg="#FFFFFF", fg="#000000",
                    mono=False, size=11)
    out = redact(st)
    text = "".join(r.text for r in out.lines[0])
    assert "1234" not in text and "연락처" in text and out.lines[0][-1].color == "#FF0000"


def test_ST_21_proportional_english_is_not_monospace(engine):
    f = font(("arial.ttf", "segoeui.ttf"), 20)
    rows = [[("The quick brown fox jumps over the lazy dog", BLACK)], [("Pack my box with five dozen liquor jugs", BLACK)],
            [("illicit willow minimum wwww mmmm", BLACK)]]
    st = styled(engine, draw(rows, LIGHT, f))
    assert not st.mono
    assert [" ".join(t.split()) for t in text_lines(st)][0] == "The quick brown fox jumps over the lazy dog"


def test_ST_22_quote_marks_the_reader_skipped_are_not_bullets(user):
    flat = "\n".join(text_lines(user))
    assert "•" not in flat and flat.lstrip().startswith("●"), flat[:200]
    assert "도형PPT of a diagram" in " ".join(flat.split()), flat[:300]


def test_ST_23_two_columns_side_by_side_keep_their_gap(engine):
    f = font(SANS, 20)
    st = styled(engine, draw([[("이름", BLACK), ("                    홍길동", BLACK)],
                              [("부서", BLACK), ("                    영업팀", BLACK)]], LIGHT, f))
    lines = text_lines(st)
    assert all(len(t.split()) == 2 and "   " in t for t in lines), lines
