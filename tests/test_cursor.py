"""The mouse pointer while choosing what to capture (BUG-102): after text mode the next capture
started with the text pointer (I-beam) - it looked like a place to type. Choosing an area always
shows the capture pointer (a crosshair with a small selection frame); tools get their own."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from capture_tool.core.ocr import OcrLine
from tests.test_app import FakeOcr, drag, make  # noqa: F401 (fixture)

LINES = [OcrLine("글자 인식", (10, 10, 90, 20), 0.9)]


def is_capture_pointer(ov) -> bool:
    cur = ov.cursor()
    return cur.shape() == Qt.BitmapCursor and not cur.pixmap().isNull()


def test_CUR_01_choosing_an_area_shows_the_capture_pointer(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    assert is_capture_pointer(ov)
    pm, hot = ov.cursor().pixmap(), ov.cursor().hotSpot()
    assert 24 <= pm.width() / pm.devicePixelRatio() <= 48
    assert 4 <= hot.x() <= pm.width() and 4 <= hot.y() <= pm.height()          # points with the crosshair's centre


def test_CUR_02_after_text_mode_the_next_capture_is_not_a_text_pointer(make):
    c = make(ocr=FakeOcr(LINES))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.side_bar.trigger("text")
    assert ov.cursor().shape() == Qt.IBeamCursor                                # picking letters: the text pointer
    QTest.keyClick(ov, Qt.Key_Escape)
    c.start_capture()
    assert is_capture_pointer(c.overlays[0]), c.overlays[0].cursor().shape()


def test_CUR_03_after_a_reading_that_found_nothing(make):
    c = make(ocr=FakeOcr([]))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.side_bar.trigger("text")
    c.cancel()
    c.start_capture()
    assert is_capture_pointer(c.overlays[0])


def test_CUR_04_once_an_area_is_chosen_the_tools_have_their_own_pointer(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert ov.cursor().shape() == Qt.CrossCursor                                # drawing
    ov.set_tool("select")
    assert ov.cursor().shape() == Qt.ArrowCursor
    c.cancel()
    c.start_capture()
    assert is_capture_pointer(c.overlays[0])                                    # a new capture: choosing again


def test_CUR_05_the_pointer_is_visible_on_dark_and_light(qt_app):
    from capture_tool.app.overlay import capture_cursor
    img = capture_cursor().pixmap().toImage()
    dark = light = 0
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixelColor(x, y)
            if px.alpha() > 200:
                dark += px.lightness() < 80
                light += px.lightness() > 200
    assert dark > 30 and light > 30, (dark, light)                              # dark lines with a light edge
