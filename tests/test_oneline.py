"""Text mode: a "줄바꿈 없이" copy that joins the recognized lines into one paragraph (line breaks
removed), next to the existing 전체 복사. Personal data is still hidden."""
from capture_tool.core.clipboard_payload import HTML, UNICODE
from capture_tool.core.ocr import OcrLine
from tests.test_app import FakeOcr, _editing, make  # noqa: F401 (fixture)

LINES = [OcrLine("회의는 수요일", (10, 10, 120, 20), 0.99), OcrLine("오후 세 시", (10, 40, 90, 20), 0.98),
         OcrLine("담당 010-1234-5678", (10, 70, 160, 20), 0.98)]


def text_mode(make, **kw):
    c, ov = _editing(make, ocr=FakeOcr(LINES), **kw)
    ov.side_bar.trigger("text")
    return c, ov


def test_ONE_01_button_exists(make):
    c, ov = text_mode(make)
    assert "oneline" in ov.ocr_bar.buttons and "줄바꿈" in ov.ocr_bar.buttons["oneline"].text()


def test_ONE_02_copies_text_with_line_breaks_removed(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("oneline")
    out = c.clipboard.last[UNICODE]
    assert "\n" not in out and "\r" not in out
    assert out.startswith("회의는 수요일 오후 세 시 담당")
    assert "1234" not in out                                   # personal data still hidden
    assert "줄바꿈" in c.messages[-1]


def test_ONE_03_single_line_is_just_that_line(make):
    c, ov = _editing(make, ocr=FakeOcr([OcrLine("한 줄입니다", (10, 10, 100, 20), 0.9)]))
    ov.side_bar.trigger("text")
    ov.ocr_bar.trigger("oneline")
    assert c.clipboard.last[UNICODE] == "한 줄입니다"


def test_ONE_04_html_is_one_paragraph_for_editors(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("oneline")
    h = c.clipboard.last.get(HTML, b"").decode("utf-8", "replace")
    assert "<br" not in h.split("<!--StartFragment-->")[-1]
