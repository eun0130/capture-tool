"""회전: ±90° turns a capture and opens it in the edit window; in the edit window the picture turns
in place (the window, its zoom and bars stay - BUG-113), and every button works on the turned picture."""
import cv2
import numpy as np
from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.export import rotate90
from capture_tool.core.settings import Settings
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _png(c):
    return cv2.imdecode(np.frombuffer(c.clipboard.last[PNG], np.uint8), cv2.IMREAD_UNCHANGED)


def test_ROT_01_rotate90_turns_the_pixels_both_ways():
    img = np.zeros((2, 3, 3), np.uint8)
    img[0, 2] = (1, 2, 3)                       # top-right pixel
    r = rotate90(img, +90)                      # clockwise: top-right -> bottom-right
    assert r.shape[:2] == (3, 2) and tuple(r[2, 1]) == (1, 2, 3)
    l = rotate90(img, -90)                      # counter-clockwise: top-right -> top-left
    assert l.shape[:2] == (3, 2) and tuple(l[0, 0]) == (1, 2, 3)
    assert np.array_equal(rotate90(rotate90(img, 90), -90), img)


def test_ROT_02_buttons_are_in_the_bar(make):
    c = make()
    c.start_capture()
    sb = c.overlays[0].side_bar
    assert "rotate_left" in sb.buttons and "rotate_right" in sb.buttons


def test_ROT_03_rotating_a_capture_opens_it_turned_in_the_edit_window(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))          # 400 x 300
    c.on_toolbar_action("rotate_right")
    assert c.editor is not None
    assert c.editor.canvas.image.shape[:2] == (400, 300)   # turned: 300 wide, 400 tall
    assert "회전" in c.messages[-1]
    assert _png(c).shape[:2] == (400, 300)                 # and already on the clipboard


def test_ROT_04_rotating_again_in_the_edit_window_keeps_turning(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    c.on_toolbar_action("rotate_left")
    assert c.editor.canvas.image.shape[:2] == (400, 300)
    c.on_toolbar_action("rotate_left")
    assert c.editor.canvas.image.shape[:2] == (300, 400)   # two quarter turns: upside down, same size
    c.on_toolbar_action("rotate_right")
    assert c.editor.canvas.image.shape[:2] == (400, 300)


def test_ROT_05_drawings_are_baked_in_before_turning(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.set_tool("rect")
    ov.set_color("#E03131")
    drag(ov, (120, 120), (200, 160))                      # a red box near the top-left
    c.on_toolbar_action("rotate_right")
    img = c.editor.canvas.image
    red = (img[:, :, 2] > 150) & (img[:, :, 1] < 100) & (img[:, :, 0] < 100)
    ys, xs = np.nonzero(red)
    assert len(xs) > 20 and xs.mean() > img.shape[1] * 0.5   # the box went to the top-RIGHT


def test_ROT_06_turning_in_the_edit_window_keeps_the_window(make):
    """BUG-113: the edit window closed and a new one opened (a flash, zoom and place reset)."""
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.set_tool("rect")
    ov.set_color("#E03131")
    drag(ov, (120, 120), (200, 160))
    c.on_toolbar_action("rotate_right")
    ed = c.editor
    ed.set_zoom(2.0)
    c.on_toolbar_action("rotate_right")
    assert c.editor is ed and ed.isVisible()                  # the same window ...
    assert ed.zoom == 2.0                                     # ... as it was
    assert ed.canvas.image.shape[:2] == (300, 400)            # two quarter turns: upside down
    assert "400 × 300" in ed.windowTitle()                 # width × height
    assert _png(c).shape[:2] == (300, 400)                    # copied again
    assert c.session.selection.w == 400 and c.session.selection.h == 300
    assert c.session.document.shapes == []                    # the box is part of the picture now
    img = ed.canvas.image
    red = (img[:, :, 2] > 150) & (img[:, :, 1] < 100) & (img[:, :, 0] < 100)
    ys, xs = np.nonzero(red)
    assert len(xs) > 20 and xs.mean() > img.shape[1] * 0.5 and ys.mean() > img.shape[0] * 0.5   # bottom-right
    assert "회전" in c.messages[-1]


def test_ROT_07_boxes_can_be_drawn_one_after_another_after_turning(make):
    """The user's report: after turning, drawing stopped after one box."""
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    c.on_toolbar_action("rotate_left")
    cv = c.editor.canvas
    cv.set_tool("rect")
    drag(cv, (20, 20), (80, 60))
    drag(cv, (100, 20), (160, 60))
    c.on_toolbar_action("rotate_left")                        # in place: keep drawing on the turned picture
    cv = c.editor.canvas
    cv.set_tool("ellipse")
    drag(cv, (20, 20), (80, 60))
    drag(cv, (100, 20), (160, 60))
    assert [s.kind for s in c.session.document.shapes] == ["ellipse", "ellipse"]


def test_ROT_08_auto_save_rewrites_the_file_with_the_turned_picture(make, tmp_path):
    c = make(settings=Settings(save_dir=str(tmp_path / "shots"), auto_save=True))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    c.on_toolbar_action("rotate_right")                       # saved once: 300 wide, 400 tall
    path = c._editor_path
    assert path is not None and cv2.imread(str(path)).shape[:2] == (400, 300)
    c.on_toolbar_action("rotate_right")                       # in place, nothing drawn
    c.cancel()                                                # Esc: that same file now holds the turned picture
    files = sorted((tmp_path / "shots").glob("*.png"))
    assert files == [path], files
    assert cv2.imread(str(path)).shape[:2] == (300, 400)
