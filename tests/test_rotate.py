"""회전: ±90° turns the capture (or the picture in the edit window) and opens it in the edit window,
where every button works on the turned picture."""
import cv2
import numpy as np
from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.export import rotate90
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
