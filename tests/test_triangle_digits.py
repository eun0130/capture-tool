"""도형PPT of a quiz picture (BUG): a bold digit read as text still had its top/bottom curves left
over as tiny pictures, so the digit looked broken in PowerPoint ("3" → "ㄷ"). A digit that was read
as text must not also leave picture fragments on top of it. Background and the big shapes stay."""
import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from capture_tool.core.ocr import OcrEngine
from capture_tool.core.shapes import recognize_layout

DATA = __import__("pathlib").Path(__file__).parent / "data"
FONTS = __import__("pathlib").Path("C:/Windows/Fonts")


@pytest.fixture(scope="module")
def ocr():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def _overlaps(p, t, grow=0.3):
    gx, gy = t.w * grow, t.h * grow
    return (p.x < t.x + t.w + gx and p.x + p.w > t.x - gx
            and p.y < t.y + t.h + gy and p.y + p.h > t.y - gy)


def test_TRID_01_a_digit_read_as_text_leaves_no_picture_on_it(ocr):
    img = cv2.imread(str(DATA / "triangle_quiz.png"))
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    det = recognize_layout(img, lines, lambda c: [(l.text, l.box) for l in ocr.recognize(c)], 96)
    pics = [d for d in det if d.kind == "picture"]
    for t in [d for d in det if d.kind == "text" and d.text and d.text.strip() in ("3", "6")]:
        on = [p for p in pics if _overlaps(p, t)]
        assert not on, (t.text, [(p.x, p.y, p.w, p.h) for p in on])


def test_TRID_02_background_and_the_triangle_survive(ocr):
    img = cv2.imread(str(DATA / "triangle_quiz.png"))
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    det = recognize_layout(img, lines, lambda c: [(l.text, l.box) for l in ocr.recognize(c)], 96)
    assert any(d.kind == "triangle" for d in det)
    big = [d for d in det if d.kind in ("rect", "roundRect") and d.w > 300 and d.fill]
    assert big, "the page background rectangle is kept"


def _digit_card(fontname, size, digit="3", bold=True):
    p = FONTS / fontname
    if not p.exists():
        pytest.skip("font missing")
    f = ImageFont.truetype(str(p), size)
    im = Image.new("RGB", (160, size + 60), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((60, 30), digit, font=f, fill=(20, 160, 90))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


@pytest.mark.parametrize("fontname,size,digit", [("malgunbd.ttf", 44, "3"), ("malgunbd.ttf", 60, "3"),
                                                 ("malgunbd.ttf", 44, "8"), ("arialbd.ttf", 48, "5")])
def test_TRID_03_drawn_bold_digits_do_not_fragment(ocr, fontname, size, digit):
    img = _digit_card(fontname, size, digit)
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    det = recognize_layout(img, lines, lambda c: [(l.text, l.box) for l in ocr.recognize(c)], 96)
    texts = [d for d in det if d.kind == "text" and d.text and digit in d.text]
    if not texts:
        pytest.skip("digit not read as text")
    pics = [d for d in det if d.kind == "picture"]
    assert not [p for p in pics if _overlaps(p, texts[0])], [(p.x, p.y, p.w, p.h) for p in pics]
