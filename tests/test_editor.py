"""Edit window: a scroll capture (or a whole-window capture across monitors) opens with the same
tools as a normal capture — drawing palette, text (OCR), PPT, shapes, links, pin — enlarged."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import GVML, PNG, UNICODE
from capture_tool.core.ocr import OcrLine
from tests.scrollsim import FakePage, make_page
from tests.test_app import FakeOcr, FakePpt, decode_png, drag
from tests.test_scroll_app import VIEW, ScrollScreen, make, select_view  # noqa: F401 (fixture)


class SpyOcr(FakeOcr):
    def __init__(self, lines=()):
        super().__init__(lines)
        self.images = []

    def recognize(self, img):
        self.images.append(img.shape)
        return self.lines


def scrolled(make, page_h=1500, ocr=None, **settings_kw):
    fp = FakePage(make_page(page_h), vh=400)
    scr = ScrollScreen(fp, wins=(), browsers=())
    c = make(scr)
    for k, v in settings_kw.items():
        setattr(c.settings, k, v)
    if ocr is not None:
        c.ocr = ocr
    select_view(c).side_bar.trigger("scroll")
    return c, fp


def canvas_point(ed, x, y):
    """Widget point on the canvas for image pixel (x, y) at the current zoom."""
    cv = ed.canvas
    return QPoint(round(x / cv.scale), round(y / cv.scale))


def test_ED_01_scroll_capture_opens_the_editor_and_is_already_copied(make):
    c, fp = scrolled(make)
    ed = c.editor
    assert ed is not None and ed.isVisible()
    assert ed.canvas.image.shape[:2] == (1500, 480)
    assert c.session.selection.w == 480 and c.session.selection.h == 1500
    assert np.array_equal(decode_png(c.clipboard.last[PNG]), fp.expected())   # Ctrl+V still works
    assert ed.canvas.toolbar.isVisible() and ed.canvas.side_bar.isVisible()


def test_ED_02_draw_with_the_palette_then_copy(make):
    c, _ = scrolled(make)
    ed = c.editor
    cv = ed.canvas
    cv.set_tool("rect")
    cv.set_color("#E03131")
    drag(cv, (canvas_point(ed, 50, 1200).x(), canvas_point(ed, 50, 1200).y()),
         (canvas_point(ed, 200, 1300).x(), canvas_point(ed, 200, 1300).y()))
    assert len(c.session.document.shapes) == 1
    cv.side_bar.trigger("copy")
    img = decode_png(c.clipboard.last[PNG])
    assert img.shape[:2] == (1500, 480)
    red = (img[:, :, 2] > 180) & (img[:, :, 1] < 90)
    ys = np.nonzero(red.any(axis=1))[0]
    assert ys.min() >= 1190 and ys.max() <= 1310               # drawn where it was put, deep in the page
    assert c.editor is None and not ed.isVisible()


def test_ED_03_text_recognition_on_the_whole_tall_image(make):
    ocr = SpyOcr([OcrLine("첫 줄", (10, 20, 80, 20), 0.9), OcrLine("마지막 줄", (10, 1400, 120, 20), 0.9)])
    c, _ = scrolled(make, ocr=ocr)
    cv = c.editor.canvas
    cv.side_bar.trigger("text")
    assert ocr.images[-1][:2] == (1500, 480)
    assert cv.ocr_lines is not None and cv.ocr_bar.isVisible()
    assert "마지막 줄" in c.clipboard.last[UNICODE]
    p1, p2 = canvas_point(c.editor, 5, 1395), canvas_point(c.editor, 200, 1425)
    drag(cv, (p1.x(), p1.y()), (p2.x(), p2.y()))
    assert c.clipboard.last[UNICODE] == "마지막 줄"


def test_ED_04_ppt_and_shapes(make):
    from capture_tool.platform.powerpoint import ClipboardShapes, Picture
    c, _ = scrolled(make)
    c.powerpoint = FakePpt()
    c.editor.canvas.side_bar.trigger("ppt")
    assert isinstance(c.powerpoint.items[-1], Picture) and c.powerpoint.items[-1].image.shape[0] == 1500
    assert c.editor is None
    c2, _ = scrolled(make)
    c2.powerpoint = FakePpt()
    cv = c2.editor.canvas
    cv.set_tool("rect")
    drag(cv, (20, 20), (120, 80))
    cv.side_bar.trigger("ppt_shapes")
    assert GVML in c2.clipboard.last and isinstance(c2.powerpoint.items[-1], ClipboardShapes)


def test_ED_05_links_save_and_pin(make, tmp_path):
    c, _ = scrolled(make, share_consent=True)
    c.uploader = lambda png, expiry: "https://litter.catbox.moe/ed.png"
    c.editor.canvas.side_bar.trigger("link_web")
    assert c.clipboard.last[UNICODE] == "https://litter.catbox.moe/ed.png"
    c2, _ = scrolled(make)
    c2.editor.canvas.side_bar.trigger("save_as")
    assert (tmp_path / "scroll.png").exists()
    c3, _ = scrolled(make, page_h=6000)
    c3.editor.canvas.side_bar.trigger("pin")
    pin = c3.pins[-1]
    assert pin.height() <= 1000 and pin.image.shape[0] == 6000   # a tall pin fits on the screen


def test_ED_06_scroll_button_is_not_offered_inside_the_editor(make):
    c, _ = scrolled(make)
    sb = c.editor.canvas.side_bar
    assert "scroll" not in sb.buttons
    from PySide6.QtWidgets import QToolButton
    assert all(b.text() != "스크롤" for b in sb.findChildren(QToolButton))   # not left drawn behind


def test_ED_07_zoom_changes_size_and_keeps_coordinates(make):
    c, _ = scrolled(make)
    ed = c.editor
    cv = ed.canvas
    ed.set_zoom(2.0)
    assert abs(cv.width() - 480 * 2 / ed.dpr) <= 2 and "200%" in ed.zoom_label.text()
    cv.set_tool("rect")
    a, b = canvas_point(ed, 100, 100), canvas_point(ed, 200, 150)
    drag(cv, (a.x(), a.y()), (b.x(), b.y()))
    (x1, y1), (x2, y2) = c.session.document.shapes[-1].points
    assert abs(x1 - 100) <= 2 and abs(y2 - 150) <= 2
    ed.zoom_by(-1)
    assert ed.zoom < 2.0
    ed.fit_width()
    assert abs(cv.width() - ed.area.viewport().width()) <= 4 or cv.width() <= ed.area.viewport().width()


def test_ED_08_ctrl_wheel_zooms(make):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    c, _ = scrolled(make)
    ed = c.editor
    z = ed.zoom
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                     Qt.ControlModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(ed.canvas, ev)
    assert ed.zoom > z


def test_ED_09_escape_closes_and_a_new_capture_can_start(make):
    c, _ = scrolled(make)
    QTest.keyClick(c.editor.canvas, Qt.Key_Escape)
    assert c.editor is None and c.start_capture()


def test_ED_10_closing_the_window_ends_the_session(make):
    c, _ = scrolled(make)
    c.editor.close()
    assert c.editor is None and c.start_capture()


def test_ED_11_hotkey_while_the_editor_is_open_says_so(make):
    c, _ = scrolled(make)
    assert not c.start_capture()
    assert any("편집 창" in m for m in c.messages) and c.editor is not None


def test_ED_12_auto_save_once_then_updated_with_drawings(make, tmp_path):
    c, _ = scrolled(make, auto_save=True)
    files = sorted((tmp_path / "shots").glob("*.png"))
    assert len(files) == 1                                      # saved the moment it was captured
    cv = c.editor.canvas
    cv.set_tool("rect")
    cv.set_color("#E03131")
    drag(cv, (20, 20), (120, 80))
    cv.side_bar.trigger("copy")
    files = sorted((tmp_path / "shots").glob("*.png"))
    assert len(files) == 1                                      # same file, now with the drawing
    img = decode_png(files[0].read_bytes())
    assert ((img[:, :, 2] > 180) & (img[:, :, 1] < 90)).any()


def test_ED_13_auto_save_and_escape_keeps_one_file(make, tmp_path):
    c, _ = scrolled(make, auto_save=True)
    QTest.keyClick(c.editor.canvas, Qt.Key_Escape)
    assert len(list((tmp_path / "shots").glob("*.png"))) == 1


def test_ED_14_mosaic_on_a_tall_image_repaints_fast(make):
    import time
    c, _ = scrolled(make, page_h=12000)
    cv = c.editor.canvas
    cv.set_tool("mosaic")
    drag(cv, (10, 10), (200, 120))
    t = time.perf_counter()
    for _ in range(5):
        cv.repaint()
    assert (time.perf_counter() - t) / 5 < 0.15


def test_ED_15_text_window_opens_on_screen(make):
    ocr = SpyOcr([OcrLine("첫 줄", (10, 20, 80, 20), 0.9)])
    c, _ = scrolled(make, ocr=ocr)
    c.editor.canvas.side_bar.trigger("text")
    c.on_ocr_action("window")
    from PySide6.QtGui import QGuiApplication
    geo = QGuiApplication.primaryScreen().virtualGeometry()
    assert c.text_panel is not None and geo.intersects(c.text_panel.frameGeometry())
