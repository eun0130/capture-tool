"""The action bar: one row right under the capture (basic), "전체" opens a second row with
everything, auto-save shows as a pressed toggle, and the bar never leaves the screen or covers
the drawing toolbar."""
import random

import pytest

from capture_tool.core.geometry import Rect, layout_action_bars
from tests.test_app import drag, make  # noqa: F401 (fixture)

BASIC = ["copy", "autosave", "text", "table", "ppt", "mail", "kakao", "search", "pin", "more"]


def selected(make, a=(100, 100), b=(400, 300), **kw):
    c = make(**kw)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, a, b)
    return c, ov


def visible(sb):
    return [k for k, b in sb.buttons.items() if not b.isHidden()]


def test_BAR_01_one_row_right_under_the_capture(make):
    c, ov = selected(make)
    sb = ov.side_bar
    g = sb.geometry()
    assert sb.isVisible() and g.width() > g.height() * 3
    assert g.top() == 300 + 8 and g.left() == 100
    assert visible(sb) == BASIC
    tb = ov.toolbar.geometry()
    assert not tb.intersects(g)


def test_BAR_02_more_opens_everything_and_is_remembered(make):
    c, ov = selected(make)
    sb = ov.side_bar
    h = sb.height()
    sb.buttons["more"].click()
    assert {"save_as", "ppt_shapes", "scroll", "link", "open_folder"} <= set(visible(sb))
    assert sb.height() > h and c.settings.bar_expanded is True
    assert "기본" in sb.buttons["more"].text()
    assert not ov.toolbar.geometry().intersects(sb.geometry())
    c.cancel()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    assert "scroll" in visible(c.overlays[0].side_bar)              # next capture: still expanded
    sb2 = c.overlays[0].side_bar
    sb2.buttons["more"].click()
    assert visible(sb2) == BASIC and c.settings.bar_expanded is False


def test_BAR_03_auto_save_toggle_shows_its_state(make):
    c, ov = selected(make)
    b = ov.side_bar.buttons["autosave"]
    assert b.isCheckable() and b.isChecked() is c.settings.auto_save is False
    b.click()
    assert c.settings.auto_save is True and b.isChecked() and "켜짐" in b.text()
    assert any("자동 저장" in m and "켰" in m for m in c.messages)
    b.click()
    assert c.settings.auto_save is False and not b.isChecked()


def test_BAR_04_selection_at_the_bottom_puts_the_bar_above(make):
    c, ov = selected(make, (100, 400), (400, 595))
    g = ov.side_bar.geometry()
    assert g.bottom() < 400 and g.top() >= 0


def test_BAR_05_full_screen_selection_keeps_the_bar_inside(make):
    c, ov = selected(make, (0, 0), (799, 599))
    g = ov.side_bar.geometry()
    assert 0 <= g.left() and g.right() <= 800 and 0 <= g.top() and g.bottom() <= 600
    assert not ov.toolbar.geometry().intersects(g)


def test_BAR_06_layout_never_leaves_the_monitor_or_overlaps(make):
    rnd = random.Random(11)
    mon = Rect(-1920, 0, 1920, 1080)
    for _ in range(3000):
        w, h = rnd.randint(1, 1920), rnd.randint(1, 1080)
        sel = Rect(mon.x + rnd.randint(0, 1920 - w), rnd.randint(0, 1080 - h), w, h)
        tb = (rnd.randint(200, 1200), rnd.randint(40, 120))
        ab = (rnd.randint(300, 1100), rnd.randint(44, 110))
        (tx, ty), (ax, ay) = layout_action_bars(sel, mon, tb, ab)
        t, a = Rect(tx, ty, *tb), Rect(ax, ay, *ab)
        for r in (t, a):
            assert mon.x <= r.x and r.right <= mon.right and mon.y <= r.y and r.bottom <= mon.bottom, (sel, r)
        assert not (t.x < a.right and a.x < t.right and t.y < a.bottom and a.y < t.bottom), (sel, t, a)


def test_BAR_07_every_action_still_works_by_name(make):
    c, ov = selected(make)
    for name in ("save_as", "ppt_shapes", "scroll", "link", "open_folder", "table", "mail", "kakao", "pin"):
        assert name in ov.side_bar.buttons


def test_BAR_08_open_folder_opens_the_save_folder(make, tmp_path):
    c, ov = selected(make)
    c.settings.save_dir = str(tmp_path)
    opened = []
    c.open_folder = opened.append
    ov.side_bar.trigger("open_folder")
    assert opened and str(opened[0]) == str(tmp_path)


def test_BAR_09_edit_window_keeps_a_column(make):
    import numpy as np
    c = make()
    c.open_editor(np.full((3000, 800, 3), 200, np.uint8), 96, "스크롤 캡처")
    sb = c.editor.canvas.side_bar
    assert sb.columns == 1 and sb.height() > sb.width()
    assert "scroll" not in sb.buttons and "save_as" in visible(sb)
