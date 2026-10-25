"""도형PPT: an option to put all the loose text into ONE text box instead of one box per line
(the current behaviour stays the default). A banner / paragraph then pastes as a single editable
text block in the same place, keeping line order, colour and page background."""
import cv2
import numpy as np
import pytest

from capture_tool.core.ocr import OcrEngine
from capture_tool.core.shapes import Detected, merge_free_text, recognize_layout
from capture_tool.platform.powerpoint import ClipboardShapes
from tests.test_app import FakeOcr, FakePpt, make  # noqa: F401 (fixture)

DATA = __import__("pathlib").Path(__file__).parent / "data"


def _text(det):
    return [d for d in det if d.kind == "text"]


pytestmark = pytest.mark.windows_contract


def test_MERGE_01_loose_text_becomes_one_box_keeping_lines():
    det = [Detected("text", 10, 10, 120, 24, text="Adobe 생성형", text_color="#E03131"),
           Detected("text", 10, 40, 140, 24, text="AI를 무제한으로", text_color="#E03131"),
           Detected("text", 10, 90, 180, 20, text="떠오른 아이디어를"),
           Detected("roundRect", 8, 130, 200, 40, fill="#E03131", text="구매하기")]
    out = merge_free_text(det)
    texts = _text(out)
    assert len(texts) == 1, [(d.text, d.y) for d in texts]
    assert texts[0].text == "Adobe 생성형\nAI를 무제한으로\n떠오른 아이디어를"
    assert texts[0].x == 10 and texts[0].y == 10 and texts[0].w >= 180 and texts[0].h >= 100
    assert any(d.kind == "roundRect" and d.text == "구매하기" for d in out)   # text inside a shape stays there
    assert texts[0].align == "l"


def test_MERGE_02_blank_rows_between_blocks_are_kept_as_empty_lines():
    det = [Detected("text", 10, 10, 80, 20, text="제목"),
           Detected("text", 10, 90, 160, 20, text="본문 첫 줄"),     # a big gap below the title
           Detected("text", 10, 118, 160, 20, text="본문 둘째 줄")]
    out = merge_free_text(det)
    assert _text(out)[0].text == "제목\n\n본문 첫 줄\n본문 둘째 줄", _text(out)[0].text


def test_MERGE_03_colour_is_kept_when_every_line_shares_one():
    det = [Detected("text", 10, 10, 80, 20, text="빨강 1", text_color="#E03131"),
           Detected("text", 10, 36, 80, 20, text="빨강 2", text_color="#E23434")]
    assert merge_free_text(det)[0].text_color.upper() in ("#E03131", "#E23434")


def test_MERGE_04_nothing_to_merge_is_unchanged():
    det = [Detected("rect", 0, 0, 50, 50, fill="#FFF"), Detected("text", 5, 5, 40, 20, text="혼자")]
    assert merge_free_text(det) == det
    assert merge_free_text([]) == []


def test_MERGE_05_two_words_on_one_row_join_with_a_space():
    det = [Detected("text", 10, 10, 40, 20, text="떠오른"), Detected("text", 60, 12, 60, 20, text="아이디어를"),
           Detected("text", 10, 40, 120, 20, text="다음 줄")]
    assert merge_free_text(det)[0].text == "떠오른 아이디어를\n다음 줄"


@pytest.fixture(scope="module")
def ocr():
    e = OcrEngine()
    try:
        e._load()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"OCR models not available: {ex}")
    return e


def test_MERGE_06_adobe_banner_merges_to_one_box(ocr):
    img = cv2.imread(str(DATA / "adobe_banner.png"))
    lines = [(l.text, l.box, l.score) for l in ocr.recognize(img)]
    det = recognize_layout(img, lines, lambda c: [(l.text, l.box) for l in ocr.recognize(c)], 96)
    before = len(_text(det))
    out = merge_free_text(det)
    assert before >= 4 and len(_text(out)) == 1, (before, len(_text(out)))
    merged = _text(out)[0].text
    assert "생성형" in merged and "무제한으로" in merged and "표현하세요" in merged


def test_MERGE_07_the_button_offers_both_and_merge_sends_one_textbox(make):
    c = make(ocr=FakeOcr([]))
    c.powerpoint = FakePpt()
    img = cv2.imread(str(DATA / "adobe_banner.png"))
    if not getattr(c.ocr, "ready", False):
        import types
        real = OcrEngine()
        try:
            real._load()
        except Exception:  # noqa: BLE001
            pytest.skip("OCR models not available")
        c.ocr = real
    c._run_recognition_on(img, "ppt", 96, merge_text=True)
    item = c.powerpoint.items[-1]
    assert isinstance(item, ClipboardShapes)
    import io
    import zipfile
    from capture_tool.core.clipboard_payload import GVML
    xml = zipfile.ZipFile(io.BytesIO(c.clipboard.last[GVML])).read("clipboard/drawings/drawing1.xml").decode()
    assert xml.count("<a:t>") <= 4, xml.count("<a:t>")        # a few shape labels + one merged block, not ~10


def test_MERGE_08_sidebar_offers_the_merge_choice(make):
    c = make()
    c.start_capture()
    sb = c.overlays[0].side_bar
    assert "ppt_shapes" in sb.buttons
    names = [a for a in sb.shapes_menu_actions()] if hasattr(sb, "shapes_menu_actions") else []
    assert "ppt_merge" in names, names
