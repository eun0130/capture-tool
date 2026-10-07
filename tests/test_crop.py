"""자르기 (X): drag a box over the capture - only that part is kept. Works in a normal capture and
in the edit window (scroll capture, opened pictures); every output (copy, save, PPT, text) gets the
cut part; Ctrl+Z brings the whole back; a new box replaces the old one."""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import PNG, UNICODE
from capture_tool.core.ocr import OcrLine
from tests.test_app import FakeOcr, drag, make  # noqa: F401 (fixture)
from tests.test_editor import canvas_point, scrolled


def png(c):
    return cv2.imdecode(np.frombuffer(c.clipboard.last[PNG], np.uint8), cv2.IMREAD_UNCHANGED)


def editing(make, **kw):
    c = make(**kw)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))                     # a 400 x 300 capture
    return c, ov


def test_CROP_01_tool_exists_with_key_and_tip(make):
    c, ov = editing(make)
    assert "crop" in ov.toolbar.buttons and "자르기" in ov.toolbar.buttons["crop"].toolTip()
    QTest.keyClick(ov, Qt.Key_X)
    assert ov.tool == "crop"


def test_CROP_02_box_cuts_the_copy_to_its_size(make):
    c, ov = editing(make)
    ov.set_tool("crop")
    drag(ov, (150, 130), (350, 280))                     # 200 x 150 inside the capture
    c.finish("copy")
    img = png(c)
    assert abs(img.shape[1] - 200) <= 2 and abs(img.shape[0] - 150) <= 2, img.shape
    if img.shape[2] == 4:
        assert img[:, :, 3].min() == 255                 # a box: nothing see-through


def test_CROP_03_box_dragged_backwards_or_past_the_edge(make):
    c, ov = editing(make)
    ov.set_tool("crop")
    drag(ov, (450, 380), (50, 60))                       # right-to-left, beyond the capture
    c.finish("copy")
    assert png(c).shape[:2] == (280, 350)                 # from the press point to the capture's corner (clamped)


def test_CROP_04_tiny_box_is_ignored_with_a_message(make):
    c, ov = editing(make)
    ov.set_tool("crop")
    drag(ov, (200, 200), (204, 203))
    assert c.session.document.clip is None and "작" in c.messages[-1]


def test_CROP_05_undo_brings_the_whole_capture_back_and_new_box_replaces(make):
    c, ov = editing(make)
    ov.set_tool("crop")
    drag(ov, (150, 130), (350, 280))
    drag(ov, (120, 110), (220, 210))                     # a second box: this one counts
    QTest.keyClick(ov, Qt.Key_Z, Qt.ControlModifier)
    QTest.keyClick(ov, Qt.Key_Z, Qt.ControlModifier)
    c.finish("copy")
    assert png(c).shape[:2] == (300, 400)
    c2, ov2 = editing(make)
    ov2.set_tool("crop")
    drag(ov2, (150, 130), (350, 280))
    drag(ov2, (120, 110), (220, 210))
    c2.finish("copy")
    assert abs(png(c2).shape[1] - 100) <= 2


def test_CROP_06_drawings_are_kept_inside_the_box(make):
    c, ov = editing(make)
    ov.set_tool("rect")
    ov.set_color("#E03131")
    drag(ov, (160, 140), (260, 240))
    ov.set_tool("crop")
    drag(ov, (150, 130), (350, 280))
    c.finish("copy")
    img = png(c)[:, :, :3]
    red = (img[:, :, 2] > 180) & (img[:, :, 1] < 90)
    assert red.sum() > 50


def test_CROP_07_text_reads_only_the_kept_part(make):
    lines = [OcrLine("남길 글", (60, 40, 80, 20), 0.9), OcrLine("잘린 글", (300, 250, 80, 20), 0.9)]
    c, ov = editing(make, ocr=FakeOcr(lines))
    seen = []
    c.ocr.recognize = lambda img: (seen.append(img.copy()), lines)[1]
    ov.set_tool("crop")
    drag(ov, (150, 130), (350, 280))
    ov.side_bar.trigger("text")
    img = seen[-1]
    assert img.shape[:2] == (300, 400) and (img[200:, :] == 255).all()          # cut away: blank


def test_CROP_08_auto_save_keeps_the_cut_picture(make, tmp_path):
    c, ov = editing(make)
    c.settings.auto_save = True
    ov.set_tool("crop")
    drag(ov, (150, 130), (350, 280))
    c.finish("copy")
    files = list((tmp_path / "shots").glob("*.png"))
    assert files, list(tmp_path.rglob("*"))
    img = cv2.imdecode(np.fromfile(str(files[0]), np.uint8), cv2.IMREAD_UNCHANGED)
    assert abs(img.shape[1] - 200) <= 2 and abs(img.shape[0] - 150) <= 2


def test_CROP_09_scroll_capture_can_be_cut_in_the_edit_window(make):
    c, fp = scrolled(make, page_h=1500)
    ed = c.editor
    cv = ed.canvas
    cv.set_tool("crop")
    a, b = canvas_point(ed, 20, 300), canvas_point(ed, 420, 900)
    drag(cv, (a.x(), a.y()), (b.x(), b.y()))
    c.finish("copy")
    img = png(c)
    assert abs(img.shape[1] - 400) <= 3 and abs(img.shape[0] - 600) <= 3, img.shape
    want = fp.expected()[300:900, 20:420]
    assert np.abs(img[:, :, :3].astype(int)[:595, :395] - want.astype(int)[:595, :395]).mean() < 3


def test_CROP_10_scroll_capture_cut_at_another_zoom(make):
    c, fp = scrolled(make, page_h=1500)
    ed = c.editor
    ed.set_zoom(0.5)
    cv = ed.canvas
    cv.set_tool("crop")
    a, b = canvas_point(ed, 0, 1000), canvas_point(ed, 480, 1500)
    drag(cv, (a.x(), a.y()), (b.x(), b.y()))
    c.finish("copy")
    img = png(c)
    assert abs(img.shape[0] - 500) <= 4 and abs(img.shape[1] - 480) <= 4, img.shape


def test_CROP_11_opened_picture_can_be_cut(make, tmp_path):
    c = make()
    p = tmp_path / "pic.png"
    cv2.imwrite(str(p), np.full((200, 300, 3), 120, np.uint8))
    assert c.open_image_file(str(p))
    ed = c.editor
    cv = ed.canvas
    cv.set_tool("crop")
    a, b = canvas_point(ed, 50, 50), canvas_point(ed, 150, 120)
    drag(cv, (a.x(), a.y()), (b.x(), b.y()))
    c.finish("copy")
    assert abs(png(c).shape[1] - 100) <= 2 and abs(png(c).shape[0] - 70) <= 2


def test_CROP_12_guide_tells_about_it():
    from capture_tool.app import guide
    assert "자르기" in guide.as_markdown()
