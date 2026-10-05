"""Text mode copies the text with its look (HTML next to the plain text); a switch on the text
bar turns that off. Plain-text apps always get the same plain text as before."""
import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from capture_tool.core.clipboard_payload import HTML, UNICODE
from capture_tool.core.geometry import Monitor, Rect
from capture_tool.core.ocr import OcrEngine, OcrLine
from capture_tool.core.settings import Settings
from tests.test_app import FakeOcr, FakeScreen, _editing, drag, make  # noqa: F401 (fixture)

LINES = [OcrLine("def total(items):", (10, 10, 200, 22), 0.99), OcrLine("연락처 010-1234-5678", (40, 44, 220, 22), 0.98)]


def html_of(c) -> str:
    raw = c.clipboard.last.get(HTML, b"").decode("utf-8", "replace")
    return raw.split("<!--StartFragment-->")[-1].split("<!--EndFragment-->")[0]


def text_mode(make, **kw):
    c, ov = _editing(make, ocr=FakeOcr(LINES), **kw)
    ov.side_bar.trigger("text")
    return c, ov


def test_STA_01_text_copy_carries_the_look_and_the_same_plain_text(make):
    c, ov = text_mode(make)
    h = html_of(c)
    assert "<td" in h and "font-family" in h and "<br>" in h, h[-400:]
    from capture_tool.core.redact import mask
    assert c.clipboard.last[UNICODE].replace("\r\n", "\n") == "def total(items):\n" + mask("연락처 010-1234-5678")
    assert "1234" not in c.clipboard.last[UNICODE]
    assert "서식" in c.messages[-1]


def test_STA_02_switched_off_it_is_plain_as_before(make):
    c, ov = text_mode(make, settings=Settings(styled_text=False))
    h = html_of(c)
    assert "<td" not in h and "font-family" not in h
    assert "서식" not in c.messages[-1]


def test_STA_03_the_bar_switch_flips_it_remembers_and_copies_again(make):
    c, ov = text_mode(make)
    b = ov.ocr_bar.buttons["styled"]
    assert b.isCheckable() and b.isChecked()
    b.click()
    assert c.settings.styled_text is False and "<td" not in html_of(c)
    from capture_tool.core import settings as settings_io
    assert settings_io.load(c.settings_path)[0].styled_text is False
    b.click()
    assert c.settings.styled_text is True and "<td" in html_of(c)


def test_STA_04_personal_data_is_hidden_in_the_styled_copy_too(make):
    c, ov = text_mode(make)
    assert "1234" not in html_of(c) and "연락처" in html_of(c)
    c2, ov2 = text_mode(make, settings=Settings(redact_pii=False))
    assert "1234" in html_of(c2)


def test_STA_05_lines_outside_the_picture_do_not_break_the_copy(make):
    c, ov = _editing(make, ocr=FakeOcr([OcrLine("멀리 있는 글", (5000, 5000, 80, 20), 0.9), OcrLine("가까운 글", (-30, -5, 60, 20), 0.9)]))
    ov.side_bar.trigger("text")
    assert "가까운 글" in c.clipboard.last[UNICODE] and c.overlays


def test_STA_06_a_dragged_part_is_copied_as_plain_text(make):
    c, ov = text_mode(make)
    drag(ov, (100 + 10, 100 + 12), (100 + 200, 100 + 30))
    assert c.clipboard.last[UNICODE].strip() and "<td" not in html_of(c)


def test_STA_07_recognition_failure_in_the_look_keeps_the_text(make, monkeypatch):
    from capture_tool.app import controller as C

    def boom(*a, **k):
        raise RuntimeError("look failed")
    monkeypatch.setattr(C, "read_styled", boom)
    c, ov = text_mode(make)
    assert "def total(items):" in c.clipboard.last[UNICODE] and "<td" not in html_of(c)


# --- with the real reader: the lines carry their word boxes (no second reading needed) --------------

@pytest.fixture(scope="module")
def engine():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def _code_picture():
    from pathlib import Path
    p = next((Path("C:/Windows/Fonts") / n for n in ("consola.ttf", "cour.ttf") if (Path("C:/Windows/Fonts") / n).exists()), None)
    if p is None:
        pytest.skip("font missing")
    f = ImageFont.truetype(str(p), 22)
    im = Image.new("RGB", (560, 150), (30, 30, 30))
    d = ImageDraw.Draw(im)
    d.text((20, 20), "def ", font=f, fill=(249, 38, 114))
    d.text((20 + f.getlength("def "), 20), "total(items):", font=f, fill=(235, 235, 235))
    d.text((20, 60), "    return ", font=f, fill=(249, 38, 114))
    d.text((20 + f.getlength("    return "), 60), "price", font=f, fill=(235, 235, 235))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def test_STA_08_lines_carry_word_boxes_inside_their_own_box(engine):
    img = _code_picture()
    lines = engine.recognize(img)
    assert lines and all(l.words for l in lines), lines
    for l in lines:
        x, y, w, h = l.box
        for t, (x0, y0, x1, y1) in l.words:
            assert t and x - 6 <= x0 < x1 <= x + w + 6 and y - 8 <= y0 < y1 <= y + h + 8, (l, t)


def test_STA_09_real_capture_to_clipboard_keeps_keyword_colours(make, engine):
    img = _code_picture()
    mon = Monitor(0, Rect(0, 0, 560, 150), 1.0, True, "A")
    c = make(screen=FakeScreen(monitors=(mon,), image=img), ocr=engine)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (2, 2), (556, 146))
    ov.side_bar.trigger("text")
    h = html_of(c).upper()
    assert "<TD" in h and "CONSOLAS" in h, h[-600:]
    pink = [s for s in h.split("COLOR:#")[1:] if int(s[0:2], 16) > 200 and int(s[2:4], 16) < 90 and int(s[4:6], 16) < 160]
    assert pink and "DEF" in h and "&NBSP;&NBSP;&NBSP;&NBSP;" in h, h[-700:]


def test_STA_10_ppt_button_sends_the_text_with_its_look(make):
    from capture_tool.platform.powerpoint import TextItem
    from tests.test_app import FakePpt
    c, ov = text_mode(make)
    c.powerpoint = FakePpt()
    ov.side_bar.trigger("ppt")
    item = c.powerpoint.items[-1]
    assert isinstance(item, TextItem) and item.styled is not None
    assert "1234" not in "".join(r.text for l in item.styled.lines for r in l)        # personal data hidden there too


def test_STA_11_ppt_button_plain_when_switched_off_or_a_part_was_dragged(make):
    from tests.test_app import FakePpt
    c, ov = text_mode(make, settings=Settings(styled_text=False))
    c.powerpoint = FakePpt()
    ov.side_bar.trigger("ppt")
    assert c.powerpoint.items[-1].styled is None
    c2, ov2 = text_mode(make)
    c2.powerpoint = FakePpt()
    drag(ov2, (100 + 10, 100 + 12), (100 + 200, 100 + 30))
    ov2.side_bar.trigger("ppt")
    assert c2.powerpoint.items[-1].styled is None
