"""Several pinned captures on screen: choose where a pin goes (where it was taken / stacked at the
top right / the other monitor), a small bar on hover (opacity, size, copy, close) and a manager
for all pins (line them up, hide, half-transparent, close all)."""
import numpy as np
from PySide6.QtCore import QPoint, QRect

from capture_tool.core.clipboard_payload import PNG
from tests.test_app import drag, make  # noqa: F401 (fixture)


def img(w=200, h=120, v=180):
    return np.full((h, w, 3), v, np.uint8)


def screen_rect():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.primaryScreen().availableGeometry()


def overlap(a: QRect, b: QRect) -> bool:
    return a.intersects(b)


def test_PIN_01_many_pins_stay_on_screen_together(make):
    c = make()
    for i in range(3):
        c.pin(img(), QPoint(50 + i * 30, 50 + i * 30))
    assert len(c.pins) == 3 and all(p.isVisible() for p in c.pins)


def test_PIN_02_stacked_at_the_top_right_without_overlapping(make):
    c = make()
    for i in range(4):
        c.pin_stacked(img(220, 140 + 20 * i))
    g = screen_rect()
    rects = [p.frameGeometry() for p in c.pins]
    assert all(g.contains(r) for r in rects)
    assert all(r.right() >= g.right() - 260 for r in rects[:2])                     # right side
    assert not any(overlap(a, b) for i, a in enumerate(rects) for b in rects[i + 1:])


def test_PIN_03_other_monitor_with_one_screen_pins_in_place_and_says_so(make):
    c = make()
    p = c.pin_other_screen(img(), QPoint(70, 80))
    assert p.isVisible() and p.pos() == QPoint(70, 80)
    assert any("모니터가 하나" in m for m in c.messages)


def test_PIN_04_line_them_up_on_the_right(make):
    c = make()
    for i in range(5):
        c.pin(img(160, 100), QPoint(100, 100))                          # all on top of each other
    c.arrange_pins()
    g = screen_rect()
    rects = [p.frameGeometry() for p in c.pins]
    assert all(g.contains(r) for r in rects)
    assert not any(overlap(a, b) for i, a in enumerate(rects) for b in rects[i + 1:])


def test_PIN_05_hide_show_and_half_transparent(make):
    c = make()
    for _ in range(2):
        c.pin(img(), QPoint(10, 10))
    c.toggle_pins_hidden()
    assert all(not p.isVisible() for p in c.pins) and len(c.pins) == 2
    c.toggle_pins_hidden()
    assert all(p.isVisible() for p in c.pins)
    c.toggle_pins_faded()
    assert all(abs(p.windowOpacity() - 0.5) < 0.01 for p in c.pins)
    c.toggle_pins_faded()
    assert all(p.windowOpacity() > 0.99 for p in c.pins)


def test_PIN_06_close_all_asks_first(make):
    c = make()
    for _ in range(3):
        c.pin(img(), QPoint(10, 10))
    c.confirm = lambda text: False
    c.close_all_pins()
    assert len(c.pins) == 3
    asked = []
    c.confirm = lambda text: (asked.append(text), True)[1]
    c.close_all_pins()
    assert c.pins == [] and "3" in asked[0]


def test_PIN_07_hover_bar(make):
    c = make()
    p = c.pin(img(300, 200), QPoint(10, 10))
    bar = p.hover_bar
    assert set(p.bar_buttons) == {"fade", "bigger", "smaller", "copy", "close"}
    w = p.width()
    p.bar_buttons["bigger"].click()
    assert p.width() > w
    p.bar_buttons["smaller"].click()
    p.bar_buttons["fade"].click()
    assert abs(p.windowOpacity() - 0.5) < 0.01
    p.bar_buttons["fade"].click()
    assert p.windowOpacity() > 0.99
    p.bar_buttons["copy"].click()
    assert PNG in c.clipboard.last
    p.bar_buttons["close"].click()
    assert c.pins == []
    assert bar is not None


def test_PIN_08_small_pin_still_has_a_close_button(make):
    c = make()
    p = c.pin(img(40, 30), QPoint(10, 10))
    assert p.close_button is not None
    p.close_button.click()
    assert c.pins == []


def test_PIN_09_manager_lists_and_follows_the_pins(make):
    c = make()
    for _ in range(3):
        c.pin(img(), QPoint(10, 10))
    m = c.show_pin_manager()
    assert m.count() == 3 and "3" in m.title.text()
    c.pins[0].close()
    assert m.count() == 2
    m.buttons["arrange"].click()
    m.buttons["fade"].click()
    assert all(abs(p.windowOpacity() - 0.5) < 0.01 for p in c.pins)
    m.select(0)
    assert c.pins[0].isVisible()


def test_PIN_10_pin_menu_on_the_bar(qt_app):
    from capture_tool.app.side_bar import SideBar
    bar = SideBar()
    seen = []
    bar.action.connect(seen.append)
    menu = bar.pin_menu()
    acts = [a for a in menu.actions() if not a.isSeparator()]
    for a in acts:
        a.trigger()
    assert seen[:3] == ["pin", "pin_stack", "pin_other"] and "pin_manager" in seen


def test_PIN_11_pin_actions_from_a_capture(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (300, 250))
    c.on_toolbar_action("pin_stack")
    assert len(c.pins) == 1 and c.overlays == []
    c.start_capture()
    drag(c.overlays[0], (100, 100), (300, 250))
    c.on_toolbar_action("pin_other")
    assert len(c.pins) == 2
