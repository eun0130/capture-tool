"""Compatibility: Windows display scaling 100-200 %, monitors left of / above the main one
(negative coordinates), mixed scaling side by side. The selection must map to exactly the right
physical pixels, and copy / text / the edit window must work in every layout."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint

from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.geometry import Monitor, Rect
from tests.test_app import FakeClipboard, FakeOcr, decode_png, drag

SCALES = [1.0, 1.25, 1.5, 1.75, 2.0]


class GridScreen:
    """Monitors whose pixels encode their own global coordinates (to check exact mapping)."""

    def __init__(self, mons, cursor):
        self.mons, self.cursor, self.grabs = list(mons), cursor, []

    def monitors(self):
        return self.mons

    def cursor_pos(self):
        return self.cursor

    def grab(self, r):
        self.grabs.append(r)
        ys, xs = np.mgrid[r.y:r.y + r.h, r.x:r.x + r.w]
        img = np.zeros((r.h, r.w, 3), np.uint8)
        img[..., 0] = (xs % 251).astype(np.uint8)
        img[..., 1] = (ys % 241).astype(np.uint8)
        img[..., 2] = 7
        return img

    def windows(self):
        return []


@pytest.fixture
def ctl(qt_app, tmp_path):
    from capture_tool.app.controller import Controller
    from capture_tool.core.settings import Settings
    made = []

    def _make(mons, cursor):
        c = Controller(GridScreen(mons, cursor), FakeClipboard(), FakeOcr(), Settings(save_dir=str(tmp_path)),
                       tmp_path / "s.json", tmp_path, sync=True)
        made.append(c)
        return c
    yield _make
    for c in made:
        c.close_all()


def check_copy(c, ov, a, b):
    drag(ov, a, b)
    sel = c.session.selection
    assert sel is not None and sel.w > 0 and sel.h > 0
    c.finish("copy")
    img = decode_png(c.clipboard.last[PNG])
    assert img.shape[:2] == (sel.h, sel.w)
    # the top-left pixel is exactly the physical pixel at the selection's corner
    assert int(img[0, 0, 0]) == sel.x % 251 and int(img[0, 0, 1]) == sel.y % 241
    assert int(img[-1, -1, 0]) == (sel.right - 1) % 251 and int(img[-1, -1, 1]) == (sel.bottom - 1) % 241
    return sel


@pytest.mark.parametrize("scale", SCALES)
def test_DPI_01_single_monitor_at_every_scaling(ctl, scale):
    w, h = int(1280 * scale), int(800 * scale)
    c = ctl([Monitor(0, Rect(0, 0, w, h), scale, True, "A")], (10, 10))
    c.start_capture()
    ov = c.overlays[0]
    sel = check_copy(c, ov, (100, 80), (500, 380))
    assert abs(sel.w - 400 * scale) <= 2 and abs(sel.h - 300 * scale) <= 2


@pytest.mark.parametrize("left_scale,right_scale", [(1.0, 1.5), (1.5, 1.0), (1.25, 2.0), (2.0, 1.25)])
def test_DPI_02_mixed_scaling_with_a_monitor_on_the_left(ctl, left_scale, right_scale):
    left = Monitor(1, Rect(-int(1920 * left_scale), 0, int(1920 * left_scale), int(1080 * left_scale)), left_scale,
                   False, "L")
    main = Monitor(0, Rect(0, 0, int(1920 * right_scale), int(1080 * right_scale)), right_scale, True, "M")
    c = ctl([main, left], (-100, 50))                       # mouse on the left monitor
    c.start_capture()
    ov = next(o for o in c.overlays if o.monitor.name == "L")
    sel = check_copy(c, ov, (50, 60), (650, 460))
    assert sel.x < 0                                        # negative physical coordinates kept
    c.start_capture()
    ov = next(o for o in c.overlays if o.monitor.name == "M")
    check_copy(c, ov, (50, 60), (650, 460))


def test_DPI_03_monitor_above_and_portrait(ctl):
    top = Monitor(1, Rect(200, -1920, 1080, 1920), 1.0, False, "T")          # portrait, above
    main = Monitor(0, Rect(0, 0, 2560, 1440), 1.25, True, "M")
    c = ctl([main, top], (300, -1000))
    c.start_capture()
    ov = next(o for o in c.overlays if o.monitor.name == "T")
    sel = check_copy(c, ov, (20, 1500), (600, 1800))
    assert sel.y < 0


@pytest.mark.parametrize("scale", [1.25, 1.75])
def test_DPI_04_drawing_and_edit_window_at_fractional_scaling(ctl, scale):
    c = ctl([Monitor(0, Rect(0, 0, int(1600 * scale), int(900 * scale)), scale, True, "A")], (5, 5))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (600, 500))
    ov.set_tool("rect")
    drag(ov, (150, 150), (300, 250))
    (x1, y1), (x2, y2) = c.session.document.shapes[-1].points
    assert abs(x1 - 50 * scale) <= 2 and abs(y2 - 150 * scale) <= 2         # doc coords = physical px
    c.finish("copy")
    c.open_editor(np.zeros((int(3000 * scale), int(800 * scale), 3), np.uint8), 96 * scale, "dpi")
    ed = c.editor
    cv = ed.canvas
    ed.set_zoom(1.0)
    cv.set_tool("rect")
    drag(cv, (10, 10), (110, 60))
    (x1, y1), (x2, y2) = c.session.document.shapes[-1].points
    assert abs((x2 - x1) - 100 * cv.scale) <= 2                               # widget px -> image px
    c.cancel()
