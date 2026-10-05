"""번역 / 요약 straight from the capture's button bar - no need to press 텍스트 first."""
from capture_tool.app.side_bar import ACTIONS
from capture_tool.core.geometry import Monitor, Rect
from tests.test_ai_app import LINES, FakeAi, text_mode
from tests.test_app import FakeOcr, FakeScreen, _editing, make  # noqa: F401 (fixture)


def test_DIRECT_01_buttons_are_in_the_one_row_bar(make):
    c, ov = _editing(make, ocr=FakeOcr(LINES))
    rows = {a[0]: a[4] for a in ACTIONS}
    assert rows["translate"] == rows["summarize"] == "basic"
    for name in ("translate", "summarize"):
        assert ov.side_bar.buttons[name].isVisible()


def test_DIRECT_02_translate_without_text_mode(make):
    c, ov = _editing(make, ocr=FakeOcr(LINES))
    c.ai = FakeAi()
    ov.side_bar.trigger("translate")
    win = c.ai_window
    assert win is not None and win.isVisible() and win.mode == "translate"
    assert win.result_text().startswith("<ko>Quarterly revenue grew.")
    assert c.overlays and ov.ocr_lines is None             # capture stays open, still in drawing mode
    assert ov.toolbar.isVisible()


def test_DIRECT_03_summary_without_text_mode(make):
    c, ov = _editing(make, ocr=FakeOcr(LINES))
    c.ai = FakeAi()
    ov.side_bar.trigger("summarize")
    assert c.ai_window.mode == "summarize" and "매출 증가" in c.ai_window.result_text()
    assert c.ai.calls[0][0] == "summarize"


def test_DIRECT_04_no_text_says_so_and_opens_nothing(make):
    c, ov = _editing(make, ocr=FakeOcr([]))
    c.ai = FakeAi()
    ov.side_bar.trigger("translate")
    assert c.ai_window is None or not c.ai_window.isVisible()
    assert "텍스트를 찾지 못했습니다" in c.messages[-1] and not c.ai.calls


def test_DIRECT_05_in_text_mode_the_dragged_part_is_used(make):
    c, ov = text_mode(make)
    c._last_raw = "담당 010-1234-5678"                    # what a drag over the second line copied
    ov.side_bar.trigger("translate")
    assert c.ai.calls[-1][1] == "담당 010-1234-5678"


def test_DIRECT_06_bar_still_fits_a_small_screen(make):
    mon = Monitor(0, Rect(0, 0, 1280, 720), 1.0, True, "A")
    c, ov = _editing(make, screen=FakeScreen(monitors=(mon,)), ocr=FakeOcr(LINES))
    g = ov.side_bar.geometry()
    assert g.x() >= 0 and g.right() < 1280 and ov.side_bar.width() <= 1000
