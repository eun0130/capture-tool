"""도형PPT on running text with a box drawn over it (BUG-100): the text came out as a table nobody
asked for (letters of a terminal font line up in columns by themselves) and the box - its outline
cut where letters cross it - was not a shape. Checked on the user's capture and on drawn pages."""
import io
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from capture_tool.core.clipboard_payload import GVML
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.shapes import recognize_layout
from capture_tool.platform.powerpoint import ClipboardShapes, TableItem
from tests.test_app import FakePpt, make  # noqa: F401 (fixture)

DATA = Path(__file__).parent / "data"
FONTS = Path("C:/Windows/Fonts")
ORANGE = (247, 103, 7)


@pytest.fixture(scope="module")
def ocr():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def layout(ocr, img):
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    return recognize_layout(img, lines, lambda crop: [(l.text, l.box) for l in ocr.recognize(crop)], 96)


def boxes(det, rgb, tol=70):
    def near(h):
        return h and max(abs(int(h[i:i + 2], 16) - v) for i, v in zip((1, 3, 5), rgb)) <= tol
    return [d for d in det if d.kind in ("rect", "roundRect") and near(d.stroke)]


def bits_on(det, box, grow=8):
    """Lines / arrows / pictures lying on the outline of box."""
    out = []
    for d in det:
        if d.kind not in ("line", "arrow"):            # (pictures there are letters the line cut through)
            continue
        cx, cy = d.x + d.w / 2, d.y + d.h / 2
        inside = box.x - grow <= cx <= box.x + box.w + grow and box.y - grow <= cy <= box.y + box.h + grow
        deep = box.x + grow < cx < box.x + box.w - grow and box.y + grow < cy < box.y + box.h - grow
        same = d.stroke and box.stroke and max(abs(int(d.stroke[i:i + 2], 16) - int(box.stroke[i:i + 2], 16)) for i in (1, 3, 5)) <= 60
        if inside and (not deep or same):                 # on the frame, or a stray stroke in the box's own colour
            out.append((d.kind, d.x, d.y, d.w, d.h))
    return out


USER = DATA / "terminal_text_with_box.png"


def test_PT_01_running_text_is_not_a_table_in_shape_ppt(make, ocr):
    c = make(ocr=ocr)
    c.powerpoint = FakePpt()
    c._run_recognition_on(cv2.imread(str(USER)), "ppt", 96)
    item = c.powerpoint.items[-1]
    assert isinstance(item, ClipboardShapes) and not isinstance(item, TableItem) and not item.tables, item
    assert "표" not in c.messages[-1] or "표 " not in c.messages[-1].split("도형")[0], c.messages[-1]


def test_PT_02_box_drawn_over_text_is_one_shape(ocr):
    det = layout(ocr, cv2.imread(str(USER)))
    found = boxes(det, ORANGE)
    assert len(found) == 1, [(d.kind, d.x, d.y, d.w, d.h, d.stroke) for d in det if d.kind != "text"]
    b = found[0]
    assert abs(b.x - 394) <= 8 and abs(b.y - 117) <= 8 and abs(b.w - 620) <= 12 and abs(b.h - 274) <= 12, b
    assert not b.text and not b.fill, b                       # hollow: the text under it stays text
    assert not bits_on(det, b), bits_on(det, b)
    texts = [d for d in det if d.kind == "text"]
    assert sum(len(t.text.split("\n")) for t in texts) >= 8
    assert any("기호만" in (t.text or "").replace(" ", "") for t in texts)


def test_PT_03_the_box_reaches_powerpoint_as_a_shape(make, ocr):
    c = make(ocr=ocr)
    c.powerpoint = FakePpt()
    c._run_recognition_on(cv2.imread(str(USER)), "ppt", 96)
    xml = zipfile.ZipFile(io.BytesIO(c.clipboard.last[GVML])).read("clipboard/drawings/drawing1.xml").decode()
    assert 'prst="rect"' in xml or 'prst="roundRect"' in xml
    assert "F76707" in xml.upper() or "F7670" in xml.upper(), "the box's own colour"
    assert xml.upper().rindex("F76707") > xml.rindex("<a:t>"), "the box is in front of the text it was drawn over"


# --- drawn pages -----------------------------------------------------------------------------------------

TEXT = ["이 화면에서는 글자가 한 칸씩 줄을 맞춰 서 있습니다.", "터미널 글꼴은 모든 글자의 너비가 같기 때문입니다.",
        "그래서 위아래 줄의 글자가 저절로 세로로 맞습니다.", "하지만 이것은 표가 아니라 그냥 이어지는 글입니다.",
        "표로 바꾸면 낱말이 칸마다 쪼개져 읽을 수 없습니다.", "도형PPT 는 글은 글로, 상자는 상자로 옮겨야 합니다.",
        "마지막 줄까지 같은 모양으로 계속 이어집니다.", "끝."]


def page(bg, fg, box_rgb, box, mono=True, size=22, width=3):
    name = next((n for n in (("gulimche.ttc", "gulim.ttc", "malgun.ttf") if mono else ("malgun.ttf",)) if (FONTS / n).exists()), None)
    if name is None:
        pytest.skip("font missing")
    f = ImageFont.truetype(str(FONTS / name), size, index=1 if name == "gulim.ttc" else 0)
    lh = int(size * 1.7)
    im = Image.new("RGB", (980, lh * len(TEXT) + 60), bg)
    d = ImageDraw.Draw(im)
    for i, t in enumerate(TEXT):
        d.text((24, 30 + i * lh), t, font=f, fill=fg)
    if box_rgb:
        d.rectangle(box, outline=box_rgb, width=width)
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


CASES = [((31, 31, 30), (235, 235, 235), ORANGE, (300, 60, 760, 250), True),
         ((255, 255, 255), (30, 30, 30), (220, 30, 30), (120, 20, 900, 150), True),
         ((255, 255, 255), (30, 30, 30), (40, 90, 220), (200, 100, 640, 300), False)]


@pytest.mark.parametrize("bg,fg,box_rgb,box,mono", CASES)
def test_PT_04_drawn_text_with_a_box(make, ocr, bg, fg, box_rgb, box, mono):
    img = page(bg, fg, box_rgb, box, mono)
    det = layout(ocr, img)
    found = boxes(det, box_rgb)
    assert len(found) == 1, [(d.kind, d.x, d.y, d.w, d.h, d.stroke) for d in det if d.kind != "text"]
    b = found[0]
    assert abs(b.x - box[0]) <= 6 and abs(b.y - box[1]) <= 6 and abs(b.x + b.w - box[2]) <= 8 and abs(b.y + b.h - box[3]) <= 8, b
    assert not bits_on(det, b), bits_on(det, b)
    crossed = any(d.kind == "text" and d.x < b.x < d.x + d.w or d.kind == "text" and d.x < b.x + b.w < d.x + d.w for d in det)
    assert not (crossed and b.text), b.text                 # a box drawn across text holds none of it
    shown = sum(len(d.text.split("\n")) for d in det if d.text)        # lines of text, wherever they are held
    assert shown >= 6, shown
    c = make(ocr=ocr)
    c.powerpoint = FakePpt()
    c._run_recognition_on(img, "ppt", 96)
    assert isinstance(c.powerpoint.items[-1], ClipboardShapes) and not c.powerpoint.items[-1].tables


def test_PT_05_plain_terminal_text_without_a_box_is_text_too(make, ocr):
    c = make(ocr=ocr)
    c.powerpoint = FakePpt()
    c._run_recognition_on(page((31, 31, 30), (235, 235, 235), None, None), "ppt", 96)
    item = c.powerpoint.items[-1]
    assert isinstance(item, ClipboardShapes) and not item.tables, item


def test_PT_06_the_persons_own_drawing_over_text_goes_in_as_a_shape(make, ocr):
    from capture_tool.core.annotations import Shape
    img = page((31, 31, 30), (235, 235, 235), None, None)
    c = make(ocr=ocr)
    c.powerpoint = FakePpt()
    marks = [Shape("rect", [(300, 60), (760, 250)], color="#F76707")]
    c._run_recognition_on(img, "ppt", 96, final=img, user_shapes=marks)
    item = c.powerpoint.items[-1]
    assert isinstance(item, ClipboardShapes) and not item.tables, item
    xml = zipfile.ZipFile(io.BytesIO(c.clipboard.last[GVML])).read("clipboard/drawings/drawing1.xml").decode()
    assert "F76707" in xml.upper()


def test_PT_07_the_table_button_still_reads_a_table_from_word_pieces(make, ocr):
    """표 was asked for: the looser reading (columns the text finder glued) stays available there."""
    c = make(ocr=ocr)
    strict = c._best_table(cv2.imread(str(USER)), [(l.text, l.box, l.score) for l in ocr.recognize(cv2.imread(str(USER)))], [], 96,
                           asked=False)
    assert strict is None


def test_PT_08_real_tables_are_still_tables_in_shape_ppt(make, ocr):
    for name, rows in (("terminal_small_table.png", 5), ("terminal_metrics_table.png", 5)):
        c = make(ocr=ocr)
        c.powerpoint = FakePpt()
        c._run_recognition_on(cv2.imread(str(DATA / name)), "ppt", 96)
        item = c.powerpoint.items[-1]
        assert isinstance(item, TableItem) and len(item.rows) == rows, (name, item)
