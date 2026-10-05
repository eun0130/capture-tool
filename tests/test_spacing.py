"""Korean word spacing: the reader drops narrow spaces ("질문은한번에"); the blank columns of the
picture put them back (BUG-097). Checked on the user's capture and on generated text in several
sizes, colours and fonts - the rule must not depend on one picture."""
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from capture_tool.core.ocr import OcrEngine, restore_spaces
from tests.test_app import make  # noqa: F401 (fixture)

DATA = Path(__file__).parent / "data"
FONTS = Path("C:/Windows/Fonts")


@pytest.fixture(scope="module")
def engine():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def test_SPACE_01_users_dark_page(engine):
    lines = [l.text for l in engine.recognize(cv2.imread(str(DATA / "dark_doc_spacing.png")))]
    text = "\n".join(lines)
    for want in ["진행 방식", "질문은 한 번에 하나만 한다.", "질문마다 현재 이해,", "막힌 결정", "추천 답안을 짧게 제시한다",
                 "질문 형식:", "현재 이해:", "막힌 결정:", "추천 답안:", "{한 가지 질문}",
                 "답변을 받으면 결정된 내용을 짧게 갱신하고, 아직 중요한 불확실성이 남았을 때만 다음 질문을 한다.",
                 "선택지가 도움이 되면 2-3개만 제시하고, 항상 자유 입력을 허용한다.", "종료 기준",
                 "달성하려는 목표", "포함 범위와 제외 범위", "지켜야 할 제약", "완료 판단 기준"]:
        assert want in text, (want, text)


SENTENCES = [
    "질문은 한 번에 하나만 한다.",
    "다음 주 회의는 수요일 오후 세 시에 한다.",
    "아직 남은 일이 많지만 할 수 있는 것부터 한다.",
    "이 값은 두 번 더한 뒤 반으로 나눈 것이다.",
    "새 기능을 넣을 때는 설명서도 같이 고친다.",
    "표 안의 글자는 칸 그대로 옮겨야 한다.",
    "비용 3,500원, 수량 12개, 합계 42,000원",
    "올해 매출은 지난해보다 조금 더 늘었다.",
]


def _font(names, size):
    for n in names:
        p = FONTS / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    pytest.skip("font missing")


def _render(lines, font, fg, bg, pad=14, gap=10):
    boxes = [font.getbbox(t) for t in lines]
    w = max(b[2] for b in boxes) + 2 * pad
    lh = max(b[3] for b in boxes) + gap
    im = Image.new("RGB", (w, lh * len(lines) + 2 * pad), bg)
    d = ImageDraw.Draw(im)
    for i, t in enumerate(lines):
        d.text((pad, pad + i * lh), t, font=font, fill=fg)
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def _space_score(got: str, want: str):
    """(spaces kept, spaces wanted, spaces added wrongly) - comparing position by position."""
    def marks(s):
        out, i = set(), 0
        for ch in s:
            if ch == " ":
                out.add(i)
            else:
                i += 1
        return out, i
    g, gn = marks(got)
    w, wn = marks(want)
    if gn != wn:                                    # a letter was misread: spacing can't be compared
        return None
    return len(g & w), len(w), len(g - w)


CASES = [(names, size, fg, bg) for names in (("malgun.ttf",), ("malgunbd.ttf",), ("NanumGothic.ttf", "gulim.ttc"),
                                             ("batang.ttc",))
         for size in (15, 18, 24) for fg, bg in (((20, 20, 20), (255, 255, 255)), ((230, 232, 238), (13, 17, 23)))]


def test_SPACE_02_generated_text_keeps_its_spaces(engine):
    kept = wanted = wrong = compared = 0
    misses = []
    for names, size, fg, bg in CASES:
        img = _render(SENTENCES, _font(names, size), fg, bg)
        got = [l.text for l in engine.recognize(img)]
        for g, w in zip(got, SENTENCES):
            s = _space_score(g, w) if len(got) == len(SENTENCES) else None
            if s is None:
                continue
            compared += 1
            kept, wanted, wrong = kept + s[0], wanted + s[1], wrong + s[2]
            if s[0] != s[1] or s[2]:
                misses.append((names[0], size, g, w))
    assert compared >= 0.8 * len(CASES) * len(SENTENCES), compared
    assert kept >= 0.97 * wanted, (kept, wanted, misses[:8])
    assert wrong <= 0.015 * wanted, (wrong, wanted, misses[:8])


def test_ESC_01_one_escape_closes_the_capture_whatever_is_showing(make):
    """BUG-098: in text mode the first Esc only went back to drawing, so leaving took two."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from capture_tool.core.ocr import OcrLine
    from tests.test_ai_app import FakeAi
    from tests.test_app import FakeOcr, _editing
    for press in ("text", "translate", None):
        c, ov = _editing(make, ocr=FakeOcr([OcrLine("글자 인식", (10, 10, 90, 20), 0.9)]))
        c.ai = FakeAi()
        if press:
            ov.side_bar.trigger(press)
        ov.setFocus()
        QTest.keyClick(ov, Qt.Key_Escape)
        assert c.overlays == [], press


def _line(words_px, gap, h=20, inner=2):
    """A fake line: every syllable a block of ink, `inner` px between syllables, `gap` between words."""
    cols, x = [], 4
    for n in words_px:
        for _ in range(n):
            cols.append((x, x + 14))
            x += 14 + inner
        x += gap - inner
    img = np.full((h + 8, x + 8, 3), 255, np.uint8)
    for a, b in cols:
        img[4:4 + h, a:b] = 0
    return img, (0, 0, img.shape[1], img.shape[0])


def test_SPACE_03_wide_blank_becomes_a_space():
    img, box = _line([3, 2, 4], gap=10)
    assert restore_spaces(img, "가나다라마바사아자", box) == "가나다 라마 바사아자"


def test_SPACE_04_spaces_the_reader_found_stay_once():
    img, box = _line([3, 2, 4], gap=10)
    assert restore_spaces(img, "가나다 라마바사아자", box) == "가나다 라마 바사아자"
    assert restore_spaces(img, "가나다 라마 바사아자", box) == "가나다 라마 바사아자"


def test_SPACE_05_evenly_spread_letters_get_no_spaces():
    img, box = _line([9], gap=0, inner=6)             # a font that spreads every letter
    assert restore_spaces(img, "가나다라마바사아자", box) == "가나다라마바사아자"


def test_SPACE_06_no_space_inside_brackets_or_before_punctuation():
    img, box = _line([1, 3, 1], gap=10)
    assert restore_spaces(img, "{가나다}", box) == "{가나다}"
    assert restore_spaces(img, "English only", box) == "English only"       # not Korean: untouched


def test_SPACE_07_a_blank_is_judged_against_the_spaces_already_found():
    """Malgun: "지|난" has a 6 px blank where spaces are 10 px - not a space. Another font: spaces
    are 6 px. The line's own spaces (or the page's) say which it is, not a fixed size."""
    img, box = _line([2, 2, 3], gap=10)
    x = 4 + 16 * 5 + 16 + 14                          # widen the blank inside the last word to 5 px
    img[:, x - 3:x] = 255
    assert restore_spaces(img, "가나 다라 마바사", box) == "가나 다라 마바사"
    img2, box2 = _line([2, 2, 3], gap=6)
    assert restore_spaces(img2, "가나 다라마바사", box2) == "가나 다라 마바사"
    assert restore_spaces(img2, "가나다라마바사", box2, page_ratio=6 / 20) == "가나 다라 마바사"
