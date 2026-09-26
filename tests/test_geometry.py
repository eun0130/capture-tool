import pytest

from capture_tool.core.geometry import (
    Monitor,
    Rect,
    clamp_rect,
    monitor_at,
    nudge,
    order_cursor_first,
    selection_from_drag,
    to_logical,
    to_physical,
    toolbar_position,
    virtual_bounds,
)

LEFT = Monitor(id=1, rect=Rect(-1920, 0, 1920, 1080), scale=1.0)
MAIN = Monitor(id=0, rect=Rect(0, 0, 2560, 1440), scale=1.5, primary=True)
RIGHT = Monitor(id=2, rect=Rect(2560, 200, 1920, 1080), scale=1.25)
MONS = [MAIN, LEFT, RIGHT]


def test_GEO_01_rect_from_points_any_direction():
    assert Rect.from_points((100, 80), (10, 20)) == Rect(10, 20, 90, 60)
    assert Rect.from_points((10, 80), (100, 20)) == Rect(10, 20, 90, 60)
    r = Rect(10, 20, 90, 60)
    assert (r.right, r.bottom) == (100, 80)


def test_GEO_02_monitor_at_cursor():
    assert monitor_at((3000, 500), MONS) is RIGHT
    assert monitor_at((100, 100), MONS) is MAIN


def test_GEO_03_negative_coordinates():
    assert monitor_at((-500, 300), MONS) is LEFT


def test_GEO_04_cursor_outside_all_monitors_picks_nearest():
    # RIGHT starts at y=200; point above it in the gap
    assert monitor_at((3000, 50), MONS) is RIGHT
    assert monitor_at((-5000, 500), MONS) is LEFT


def test_GEO_05_boundary_belongs_to_right_monitor():
    assert monitor_at((0, 500), MONS) is MAIN
    assert monitor_at((2560, 500), MONS) is RIGHT
    assert monitor_at((2559, 500), MONS) is MAIN


def test_GEO_06_no_monitors():
    with pytest.raises(ValueError):
        monitor_at((0, 0), [])


def test_GEO_07_cursor_monitor_first_keeps_rest_order():
    assert order_cursor_first(MONS, (3000, 500)) == [RIGHT, MAIN, LEFT]
    assert order_cursor_first(MONS, (10, 10)) == [MAIN, LEFT, RIGHT]


def test_GEO_08_virtual_bounds_union():
    assert virtual_bounds(MONS) == Rect(-1920, 0, 1920 + 2560 + 1920, 1440)


def test_GEO_09_click_without_drag_is_no_selection():
    vb = virtual_bounds(MONS)
    assert selection_from_drag((50, 50), (51, 52), vb) is None
    assert selection_from_drag((50, 50), (50, 50), vb) is None


def test_GEO_10_drag_outside_screen_is_clipped():
    vb = virtual_bounds(MONS)
    r = selection_from_drag((100, 100), (99999, 99999), vb)
    assert r == Rect(100, 100, vb.right - 100, vb.bottom - 100)


def test_GEO_11_selection_across_monitors_allowed():
    vb = virtual_bounds(MONS)
    r = selection_from_drag((-300, 100), (300, 400), vb)
    assert r == Rect(-300, 100, 600, 300)


def test_GEO_12_nudge_stays_inside():
    b = Rect(0, 0, 100, 100)
    assert nudge(Rect(10, 10, 20, 20), 1, 0, b) == Rect(11, 10, 20, 20)
    assert nudge(Rect(80, 80, 20, 20), 5, 5, b) == Rect(80, 80, 20, 20)
    assert nudge(Rect(0, 0, 20, 20), -1, -1, b) == Rect(0, 0, 20, 20)


def test_clamp_rect_no_overlap_returns_none():
    assert clamp_rect(Rect(200, 200, 10, 10), Rect(0, 0, 100, 100)) is None


MON = Rect(0, 0, 1920, 1080)


def test_GEO_13_toolbar_below_when_space():
    assert toolbar_position(Rect(100, 100, 400, 300), MON, 600, 52) == (100, 408)


def test_GEO_14_toolbar_above_when_no_space_below():
    assert toolbar_position(Rect(100, 700, 400, 350), MON, 600, 52) == (100, 640)


def test_GEO_15_toolbar_inside_when_fullscreen_selection():
    x, y = toolbar_position(Rect(0, 0, 1920, 1080), MON, 600, 52)
    assert y == 1080 - 52 - 8
    assert 0 <= x <= 1920 - 600


def test_GEO_16_toolbar_shifted_left_at_right_edge():
    x, _ = toolbar_position(Rect(1800, 100, 100, 100), MON, 600, 52)
    assert x == 1920 - 600 - 8


def test_toolbar_on_negative_monitor():
    left = Rect(-1920, 0, 1920, 1080)
    x, y = toolbar_position(Rect(-1900, 100, 200, 200), left, 600, 52)
    assert x == -1900 and y == 308


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 1.75])
def test_GEO_17_dpi_round_trip(scale):
    r = Rect(101, 57, 333, 219)
    back = to_physical(to_logical(r, scale), scale)
    assert abs(back.x - r.x) <= 1 and abs(back.y - r.y) <= 1
    assert abs(back.w - r.w) <= 1 and abs(back.h - r.h) <= 1
