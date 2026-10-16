"""The on-screen message (toast) must not cover the capture or its bars (BUG-114)."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.geometry import Rect, place_toast
from tests.test_app import drag, make  # noqa: F401 (fixture)

SCREEN = Rect(0, 0, 1920, 1080)


def test_TOAST_01_free_screen_bottom_centre():
    assert place_toast((400, 50), SCREEN, []) == (760, 1080 - 50 - 60)


def test_TOAST_02_moves_away_from_the_capture_and_its_bars():
    busy = [Rect(500, 600, 900, 400), Rect(500, 1010, 300, 60)]       # a capture low on the screen + its bar
    x, y = place_toast((400, 50), SCREEN, busy)
    assert y == 60 and x == 760                                        # top centre: the next free spot
    busy = [Rect(0, 0, 1920, 1080)]                                    # everything covered: still on screen
    x, y = place_toast((400, 50), SCREEN, busy)
    assert 0 <= x <= 1520 and 0 <= y <= 1030


def test_TOAST_03_a_screen_not_at_the_origin():
    scr = Rect(1920, 0, 1920, 1080)
    assert place_toast((400, 50), scr, []) == (1920 + 760, 970)


def test_TOAST_04_controller_reports_the_capture_and_bars(make):
    c = make()
    assert c.busy_rects() == []
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    rects = c.busy_rects()
    assert any(r.w == 400 and r.h == 300 for r in rects), rects       # the chosen area
    assert len(rects) >= 2                                             # ... and at least one bar
    c.cancel()
    assert c.busy_rects() == []


def test_TOAST_05_toast_window_avoids_given_rects(qt_app):
    from PySide6.QtGui import QGuiApplication
    from capture_tool.app.toast import Toast
    t = Toast()
    g = QGuiApplication.primaryScreen().availableGeometry()
    t.show_message("x", 1500)
    assert t.y() > g.center().y()                                      # bottom by default
    t.show_message("x", 1500, avoid=[Rect(g.x(), g.y() + g.height() // 2, g.width(), g.height() // 2)])
    assert t.y() < g.center().y()                                      # the bottom half is busy: up it goes
    t.hide()
