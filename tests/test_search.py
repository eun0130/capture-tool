"""검색: find by picture (Google / Naver - the capture is on the clipboard, the person pastes it
into the search page, so nothing leaves the PC by itself) or by the capture's text (Google,
Naver, Papago translate)."""
from urllib.parse import parse_qs, urlsplit

import pytest

from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.ocr import OcrLine
from capture_tool.core.websearch import image_page, text_url
from tests.test_app import FakeOcr, drag, make  # noqa: F401 (fixture)


def test_SRCH_01_text_urls_are_encoded_and_trimmed():
    u = text_url("google", "매출 1,250억\n전년 대비 12%")
    q = parse_qs(urlsplit(u).query)
    assert u.startswith("https://www.google.com/search?") and q["q"] == ["매출 1,250억 전년 대비 12%"]
    n = text_url("naver", "a&b=c#d")
    assert parse_qs(urlsplit(n).query)["query"] == ["a&b=c#d"] and urlsplit(n).fragment == ""
    p = text_url("papago", "hello")
    assert p.startswith("https://papago.naver.com/?") and parse_qs(urlsplit(p).query)["st"] == ["hello"]
    long = text_url("google", "가" * 5000)
    assert len(parse_qs(urlsplit(long).query)["q"][0]) <= 300


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_SRCH_02_empty_text_has_no_url(text):
    assert text_url("google", text) is None


def test_SRCH_03_unknown_engine():
    with pytest.raises(ValueError):
        text_url("bing", "x")
    with pytest.raises(ValueError):
        image_page("bing")
    assert image_page("google").startswith("https://") and image_page("naver").startswith("https://")


def _capture(make, lines=()):
    c = make(ocr=FakeOcr(list(lines)))
    opened = []
    c.open_url = lambda u: (opened.append(u), True)[1]
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    return c, opened


def test_SRCH_04_picture_search_opens_the_page_with_the_capture_copied(make):
    c, opened = _capture(make)
    c.on_toolbar_action("search_img:google")
    assert c.overlays == [] and opened == [image_page("google")] and PNG in c.clipboard.last
    assert any("Ctrl+V" in m for m in c.messages)


def test_SRCH_05_text_search_reads_the_capture(make):
    c, opened = _capture(make, [OcrLine("3분기 매출", (10, 10, 100, 20), 0.99), OcrLine("1,250억", (10, 40, 80, 20), 0.99)])
    c.on_toolbar_action("search_text:naver")
    assert len(opened) == 1 and parse_qs(urlsplit(opened[0]).query)["query"] == ["3분기 매출 1,250억"]


def test_SRCH_06_text_search_without_text_opens_nothing(make):
    c, opened = _capture(make, [])
    c.on_toolbar_action("search_text:google")
    assert opened == [] and any("글자를 찾지 못" in m for m in c.messages)


def test_SRCH_07_bad_engine_name_is_ignored(make):
    c, opened = _capture(make)
    c.on_toolbar_action("search_text:bing")
    assert opened == [] and c.overlays                         # nothing happened, capture still open


def test_SRCH_08_side_bar_search_menu(qt_app):
    from capture_tool.app.side_bar import SideBar
    bar = SideBar()
    seen = []
    bar.action.connect(seen.append)
    assert "search" in bar.buttons
    menu = bar.search_menu()
    acts = [a for a in menu.actions() if not a.isSeparator() and a.isEnabled()]
    assert len(acts) == 5
    acts[0].trigger()
    acts[-1].trigger()
    assert seen == ["search_img:google", "search_text:papago"]


def test_SRCH_09_browser_failure_is_reported(make):
    c, _ = _capture(make)
    c.open_url = lambda u: False
    c.on_toolbar_action("search_img:naver")
    assert any("브라우저" in m for m in c.messages)
