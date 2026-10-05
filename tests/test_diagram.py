"""도형PPT of a diagram (cards with several lines of text, a dashed box) - BUG-099:
every line became its own text box on top of the card, the dashed box came out as dozens of
little pictures, and bits of the cards' outlines were pasted again as pictures/lines.
Checked on the user's capture and on drawn cards (the rules must not depend on one picture)."""
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from capture_tool.core.drawingml import drawing_xml
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.shapes import recognize_layout, to_drawing

DATA = Path(__file__).parent / "data"
CLOSED = ("rect", "roundRect", "ellipse", "diamond")


@pytest.fixture(scope="module")
def ocr():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def _layout(ocr, img):
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    return recognize_layout(img, lines, lambda crop: [(l.text, l.box) for l in ocr.recognize(crop)], 96)


@pytest.fixture(scope="module")
def det(ocr):
    return _layout(ocr, cv2.imread(str(DATA / "diagram_cards.png")))


def _card(det, word):
    cards = [d for d in det if d.kind in CLOSED and d.text and word in d.text.replace(" ", "")]
    assert len(cards) == 1, (word, [(d.kind, d.text) for d in det if d.text and word in d.text.replace(" ", "")])
    return cards[0]


def _inside(d, box, grow=0):
    cx, cy = d.x + d.w / 2, d.y + d.h / 2
    return box.x - grow <= cx <= box.x + box.w + grow and box.y - grow <= cy <= box.y + box.h + grow


CARDS = {"러프한요청": ("이스킬좋다는", "유튜브콘텐츠", "만들고싶어"),
         "명확한프롬프트의역설": ("좋은결과", "하지만처음엔", "원하는지모른다"),
         "deep-interview": ("현재이해", "추천답안", "나를인터뷰한다"),
         "구체화된명세": ("타겟", "메시지", "개념형", "12")}


def test_DIAG_01_a_card_holds_its_text_as_one_text(det):
    for title, parts in CARDS.items():
        card = _card(det, title)
        flat = card.text.replace(" ", "")
        for p in parts:
            assert p in flat, (title, p, card.text)
        loose = [d for d in det if d.kind == "text" and _inside(d, card)]
        assert not loose, (title, [d.text for d in loose])


def test_DIAG_02_blank_lines_between_title_and_body_are_kept(det):
    card = _card(det, "러프한요청")
    lines = card.text.split("\n")
    assert lines[0].replace(" ", "") == "러프한요청" and lines[1] == "" and len(lines) == 5, lines


def test_DIAG_03_left_aligned_card_stays_left_aligned(det):
    assert _card(det, "구체화된명세").align == "l"
    assert _card(det, "러프한요청").align == "ctr" and _card(det, "deep-interview").align == "ctr"


def test_DIAG_04_dashed_box_is_one_dashed_shape(det):
    box = _card(det, "바로실행하면")
    assert box.dash and abs(box.x - 121) <= 8 and abs(box.y - 389) <= 8 and abs(box.w - 526) <= 14 and abs(box.h - 141) <= 14, box
    assert "추측한다" in box.text.replace(" ", "") and "상태가되기쉽다" in box.text.replace(" ", "")
    bits = [d for d in det if d.kind in ("picture", "line", "arrow") and _inside(d, box, grow=6)]
    assert not bits, [(d.kind, d.x, d.y, d.w, d.h) for d in bits]


def test_DIAG_05_no_bits_of_a_cards_own_outline(det):
    for title in CARDS:
        card = _card(det, title)
        bits = [d for d in det if d.kind in ("picture", "line") and _inside(d, card, grow=3)]
        assert not bits, (title, [(d.kind, d.x, d.y, d.w, d.h) for d in bits])


def test_DIAG_06_powerpoint_gets_one_text_per_card_and_a_dashed_outline(det):
    shapes, conns = to_drawing(det)
    xml = drawing_xml(shapes, conns)
    assert 'prstDash val="dash"' in xml
    card = next(s for s in shapes if s.text and "러프한" in s.text)
    assert card.kind in CLOSED and card.text.count("\n") == 4
    left = next(s for s in shapes if s.text and "구체화된" in s.text)
    assert left.align == "l" and left.pad_left > 4


def test_DIAG_07_arrows_between_cards_survive(det):
    between = [d for d in det if d.kind in ("arrow", "line", "picture") and 322 <= d.x <= 680 and 205 <= d.y <= 245
               and d.w >= 18]
    assert len(between) >= 2, [(d.kind, d.x, d.y, d.w, d.h) for d in det if d.kind != "text"]


# --- drawn cards: other colours, sizes, fonts ---------------------------------------------------

def _font(size):
    for n in ("malgun.ttf", "gulim.ttc"):
        p = Path("C:/Windows/Fonts") / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    pytest.skip("font missing")


def _dashed_rect(d, box, color, dash=9, gap=6, width=2):
    x0, y0, x1, y1 = box
    for x in range(x0, x1, dash + gap):
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
    for y in range(y0, y1, dash + gap):
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)


def _draw_cards(bg, fills, size, align="ctr"):
    im = Image.new("RGB", (900, 420), bg)
    d = ImageDraw.Draw(im)
    f = _font(size)
    texts = [["주문 접수", "", "고객이 주문을", "넣으면 시작한다"], ["재고 확인", "", "창고에 물건이", "있는지 본다"],
             ["배송 준비", "", "상자에 담아", "택배로 보낸다"]]
    lh = int(size * 1.5)
    for k, (fill, lines) in enumerate(zip(fills, texts)):
        x0, y0, x1, y1 = 30 + k * 290, 40, 280 + k * 290, 200
        d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=fill, outline=(70, 70, 90), width=2)
        top = (y0 + y1) / 2 - lh * len(lines) / 2
        for i, t in enumerate(lines):
            w = d.textlength(t, font=f)
            tx = x0 + 18 if align == "l" else (x0 + x1) / 2 - w / 2
            d.text((tx, top + i * lh), t, font=f, fill=(30, 30, 40))
    _dashed_rect(d, (120, 250, 780, 390), (120, 125, 135))
    for i, t in enumerate(["바로 실행하면 어떻게 될까", "결과가 빨리 나오지만 틀리기 쉽다"]):
        w = d.textlength(t, font=f)
        d.text((450 - w / 2, 290 + i * lh), t, font=f, fill=(30, 30, 40))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


@pytest.mark.parametrize("bg,fills,size,align", [
    ((255, 255, 255), [(253, 226, 225), (254, 242, 197), (225, 243, 255)], 15, "ctr"),
    ((255, 255, 255), [(230, 240, 230), (240, 230, 250), (255, 255, 255)], 18, "ctr"),
    ((246, 247, 249), [(208, 249, 228), (253, 226, 225), (254, 242, 197)], 16, "l"),
])
def test_DIAG_08_drawn_cards(ocr, bg, fills, size, align):
    det = _layout(ocr, _draw_cards(bg, fills, size, align))
    for title, body in (("주문접수", "시작한다"), ("재고확인", "있는지본다"), ("배송준비", "택배로보낸다")):
        card = _card(det, title)
        assert body in card.text.replace(" ", "") and card.text.split("\n")[1] == "", card.text
        assert card.align == align, (title, card.align)
        assert not [d for d in det if d.kind == "text" and _inside(d, card)]
    box = _card(det, "바로실행하면")
    assert box.dash and "틀리기쉽다" in box.text.replace(" ", "")
    assert abs(box.x - 120) <= 6 and abs(box.w - 660) <= 12 and abs(box.h - 140) <= 12, box
    assert not [d for d in det if d.kind == "picture"], [(d.x, d.y, d.w, d.h) for d in det if d.kind == "picture"]
