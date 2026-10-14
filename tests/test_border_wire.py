"""테두리 · 음영 wired into the capture (fake dialog)."""
import cv2
import numpy as np
from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.export import add_border
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _editing(make, **kw):
    c = make(**kw)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))             # a 400 x 300 capture
    return c, ov


def _png(c):
    return cv2.imdecode(np.frombuffer(c.clipboard.last[PNG], np.uint8), cv2.IMREAD_UNCHANGED)


def test_BW_01_border_button_is_in_the_bar(make):
    c = make()
    c.start_capture()
    assert "border" in c.overlays[0].side_bar.buttons


def test_BW_02_border_copies_the_framed_image(make):
    c, ov = _editing(make)
    got = {}

    def ask(img, settings):
        got["in"] = img.shape[:2]
        return add_border(img, thickness=10, color=(0, 0, 0))
    c.ask_border = ask
    c.on_toolbar_action("border")
    assert got["in"] == (300, 400)
    out = _png(c)
    assert out.shape[0] == 320 and out.shape[1] == 420      # +2*10
    assert c.overlays == [] and "테두리" in c.messages[-1]


def test_BW_03_cancel_keeps_the_original_on_the_clipboard(make):
    c, ov = _editing(make)
    c.ask_border = lambda img, settings: None
    c.on_toolbar_action("border")
    assert _png(c).shape[:2] == (300, 400)


def test_BW_04_auto_save_saves_the_framed_file(make, tmp_path):
    c, ov = _editing(make)
    c.settings.auto_save = True
    c.ask_border = lambda img, s: add_border(img, thickness=5, color=(0, 0, 0))
    c.on_toolbar_action("border")
    files = list((tmp_path / "shots").glob("*.png"))
    assert files
    img = cv2.imdecode(np.fromfile(str(files[0]), np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape[0] == 310 and img.shape[1] == 410


def test_BW_05_border_works_in_the_edit_window(make, tmp_path):
    c = make()
    pic = np.full((200, 300, 3), 180, np.uint8)
    p = tmp_path / "pic.png"
    cv2.imwrite(str(p), pic)
    assert c.open_image_file(str(p))
    c.ask_border = lambda img, s: add_border(img, thickness=8, color=(0, 0, 0), shadow=True)
    c.on_toolbar_action("border")
    out = _png(c)
    assert out.shape[0] > 200 + 16 and out.shape[1] > 300 + 16   # border + shadow margin
