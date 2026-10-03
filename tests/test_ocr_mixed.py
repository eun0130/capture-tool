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


# --- v0.7.6: a capture cut tight around the text --------------------------------------------------
@pytest.mark.parametrize("crop", [(13, 52, 22, 280), (17, 48, 26, 276), (5, 60, 10, 300)])
def test_PAD_01_tight_capture_of_a_title_is_read_whole(crop):
    """Bug (v0.7.5): the red box around '매입처별 세금계산서 합계표' gave '매 ㅎ' - text touching the
    capture's edge is missed by the text finder; a margin is added before reading."""
    import cv2
    y1, y2, x1, x2 = crop
    img = cv2.imread(str(DATA / "hometax_dialog.png"))[y1:y2, x1:x2]
    text = " ".join(l.text for l in OcrEngine().recognize(img)).replace(" ", "")
    assert "매입처별세금계산서합계표" in text, text


def test_PAD_02_boxes_stay_in_the_capture_coordinates():
    import cv2
    img = cv2.imread(str(DATA / "hometax_dialog.png"))[13:52, 22:280]
    for l in OcrEngine().recognize(img):
        x, y, w, h = l.box
        assert 0 <= x and 0 <= y and x + w <= img.shape[1] and y + h <= img.shape[0], l.box


def test_CAPS_01_capital_i_in_short_capital_words():
    """Sans-serif I and l look the same: "AI", "CI", "UI" were read "Al", "Cl", "Ul"."""
    from capture_tool.core.ocr import fix_capital_i
    assert fix_capital_i("Al 매출") == "AI 매출"
    assert fix_capital_i("Cl/CD 구성") == "CI/CD 구성"
    assert fix_capital_i("KPl") == "KPI"
    assert fix_capital_i("Hello all") == "Hello all"           # ordinary words untouched
    assert fix_capital_i("Excel 파일") == "Excel 파일"
    assert fix_capital_i("A1 셀, B12") == "A1 셀, B12"           # cell references stay
    assert fix_capital_i("l") == "l" and fix_capital_i("") == ""
    assert fix_capital_i("ml 단위") == "ml 단위"


ENGLISH_TRUTH = [
    "Act as my elite academic advisor. We want to build a six-week custom course. I want",
    "to learn about how finance works in business, so I can understand how to use those",
    "skills to build my own business.",
    "1. Interview me to find my weaknesses - my baseline.",
    "2. I want to define the destination.",
    "3. Build the sequence.",
    "4. List what I should ignore for now.",
    "5. Give me weekly milestones so I can prove that I'm ready to move on.",
    "Ask me up to five questions for each of these five steps, one question at a time.",
]


def _norm(s):
    return " ".join(s.replace("’", "'").replace(". ", ".").replace(".", ". ").split())


def test_EN_01_english_paragraph_reads_cleanly():
    """User (v0.7.8): a plain English paragraph came out "e elite", "a advisor", "h t how" -
    letters from the neighbouring piece of a split line were read twice."""
    import cv2
    from capture_tool.core.ocr import full_text
    img = cv2.imread(str(DATA / "english_paragraph.png"))
    got = full_text(OcrEngine().recognize(img)).splitlines()
    assert len(got) == len(ENGLISH_TRUTH), got
    bad = [(g, t) for g, t in zip(got, ENGLISH_TRUTH) if _norm(g) != _norm(t)]
    assert not bad, bad


def test_EN_02_pronoun_i_not_l():
    from capture_tool.core.ocr import fix_capital_i
    assert fix_capital_i("so l can prove that l'm ready") == "so I can prove that I'm ready"
    assert fix_capital_i("5 l 물") == "5 l 물"                # a unit after a number stays
    assert fix_capital_i("l") == "l"


def test_CAPS_02_other_languages_untouched():
    from capture_tool.core.ocr import fix_capital_i
    for t in ("El niño comió", "crème brûlée", "à côté de l'église", "Al-Rashid"):
        assert fix_capital_i(t) == t, t


EN_SAMPLE = ("Please review the attached file before Friday's meeting and send your comments to the team lead. "
             "All invoices must be approved by the finance department. The quarterly report shows revenue of "
             "1,250,000 dollars, up 12% from Q2. I want to learn how finance works so I can build my own business.")


@pytest.mark.skipif(not Path("C:/Windows/Fonts/segoeui.ttf").exists(), reason="Windows fonts")
@pytest.mark.parametrize("font,size", [("segoeui", 14), ("arial", 13), ("calibri", 15), ("times", 16),
                                       ("consola", 14), ("verdana", 13), ("tahoma", 13), ("malgun", 14)])
def test_EN_03_english_in_common_fonts(font, size):
    """English paragraphs in the usual Windows fonts: at most 1 word in 25 wrong."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(f"C:/Windows/Fonts/{font}.ttf", size)
    img = Image.new("RGB", (640, 200), "white")
    d = ImageDraw.Draw(img)
    lines, line = [], []
    for w in EN_SAMPLE.split():
        if d.textlength(" ".join(line + [w]), font=f) > 610:
            lines.append(" ".join(line))
            line = []
        line.append(w)
    lines.append(" ".join(line))
    for i, t in enumerate(lines):
        d.text((10, 8 + i * int(size * 1.6)), t, font=f, fill=(25, 25, 25))
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    got = " ".join(l.text for l in OcrEngine().recognize(bgr)).split()
    bag = {}
    for w in got:
        bag[w] = bag.get(w, 0) + 1
    miss = 0
    for w in EN_SAMPLE.split():
        if bag.get(w, 0):
            bag[w] -= 1
        else:
            miss += 1
    assert miss <= len(EN_SAMPLE.split()) / 25, (miss, got)
