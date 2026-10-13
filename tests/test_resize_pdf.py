"""크기 줄이기 · PDF 저장 · 인쇄 wired into the capture (fakes for the dialog and printer)."""
import cv2
import numpy as np
from capture_tool.core.clipboard_payload import PNG
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _editing(make, **kw):
    c = make(**kw)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))             # a 400 x 300 capture
    return c, ov


def _png(c):
    return cv2.imdecode(np.frombuffer(c.clipboard.last[PNG], np.uint8), cv2.IMREAD_UNCHANGED)


def test_RPX_01_resize_copies_the_smaller_image(make):
    c, ov = _editing(make)
    captured = {}

    def ask(img, settings):
        captured["in"] = img.shape[:2]
        from capture_tool.core.export import resize_percent
        return resize_percent(img, 50), "png"
    c.ask_resize = ask
    c.on_toolbar_action("resize")
    assert captured["in"] == (300, 400)
    assert _png(c).shape[1] == 200 and _png(c).shape[0] == 150
    assert c.overlays == [] and "줄" in c.messages[-1]


def test_RPX_02_resize_cancel_keeps_the_original_on_the_clipboard(make):
    c, ov = _editing(make)
    c.ask_resize = lambda img, settings: None
    c.on_toolbar_action("resize")
    assert _png(c).shape[:2] == (300, 400)       # unchanged, still copied


def test_RPX_03_resize_with_auto_save_saves_the_smaller_file(make, tmp_path):
    c, ov = _editing(make)
    c.settings.auto_save = True
    from capture_tool.core.export import resize_percent
    c.ask_resize = lambda img, settings: (resize_percent(img, 25), "png")
    c.on_toolbar_action("resize")
    files = list((tmp_path / "shots").glob("*.png"))
    assert files
    img = cv2.imdecode(np.fromfile(str(files[0]), np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape[1] == 100 and img.shape[0] == 75


def test_RPX_04_pdf_saves_a_pdf_and_reveals_it(make, tmp_path):
    c, ov = _editing(make)
    revealed = []
    c.reveal_file = revealed.append
    c.on_toolbar_action("pdf")
    pdfs = list((tmp_path / "shots").glob("*.pdf")) + list((tmp_path / "fallback").glob("*.pdf"))
    assert pdfs, list(tmp_path.rglob("*"))
    data = pdfs[0].read_bytes()
    assert data[:5] == b"%PDF-"
    assert revealed and str(revealed[-1]).endswith(".pdf")
    assert PNG in c.clipboard.last                # the picture is also on the clipboard for Ctrl+V


def test_RPX_05_print_sends_the_capture_to_the_printer(make):
    c, ov = _editing(make)
    printed = []
    c.print_image = lambda img, dpi=96: (printed.append(img.shape[:2]), True)[1]
    c.on_toolbar_action("print")
    assert printed == [(300, 400)]
    assert "인쇄" in c.messages[-1]


def test_RPX_06_print_cancelled_says_so(make):
    c, ov = _editing(make)
    c.print_image = lambda img, dpi=96: False
    c.on_toolbar_action("print")
    assert "취소" in c.messages[-1] or "인쇄" in c.messages[-1]


def test_RPX_07_buttons_are_in_the_bar(make):
    c = make()
    c.start_capture()
    sb = c.overlays[0].side_bar
    for name in ("resize", "pdf", "print"):
        assert name in sb.buttons, name


def test_RPX_08_resize_of_a_cropped_capture_uses_the_cut_part(make):
    c, ov = _editing(make)
    ov.set_tool("crop")
    drag(ov, (150, 130), (350, 280))             # keep a 200 x 150 box
    got = {}

    def ask(img, settings):
        got["shape"] = img.shape[:2]
        return img, "png"
    c.ask_resize = ask
    c.on_toolbar_action("resize")
    assert abs(got["shape"][1] - 200) <= 2 and abs(got["shape"][0] - 150) <= 2


def test_RPX_09_print_helper_cancel_and_accept(qt_app):
    from capture_tool.platform.printing import print_image
    img = np.full((60, 100, 3), 180, np.uint8)

    class FakeDlg:
        def __init__(self, accept):
            self._a = accept

        def exec(self):
            from PySide6.QtWidgets import QDialog
            return QDialog.Accepted if self._a else QDialog.Rejected
    assert print_image(img, dialog_factory=lambda p: FakeDlg(False)) is False
    # accept path: a real QPrinter to a temp file, no physical printer
    import tempfile
    from PySide6.QtPrintSupport import QPrinter
    out = tempfile.mktemp(suffix=".pdf")

    def printer():
        p = QPrinter(QPrinter.HighResolution)
        p.setOutputFileName(out)
        return p
    assert print_image(img, dialog_factory=lambda p: FakeDlg(True), printer_factory=printer) is True
    import os
    assert os.path.exists(out) and os.path.getsize(out) > 500


def test_RPX_10_pdf_and_resize_work_in_the_edit_window(make, tmp_path):
    """Blindspot: a long opened/scroll capture in the edit window. PDF splits into pages, resize
    and print use the shared path."""
    c = make()
    big = np.full((3000, 500, 3), 200, np.uint8)
    p = tmp_path / "big.png"
    cv2.imwrite(str(p), big)
    assert c.open_image_file(str(p))
    c.on_toolbar_action("pdf")
    pdfs = list(tmp_path.rglob("*.pdf"))
    assert pdfs and pdfs[0].read_bytes().count(b"/MediaBox") >= 3      # a tall capture → several pages
    assert c.open_image_file(str(p))
    c.ask_resize = lambda img, s: (cv2.resize(img, (250, 1500)), "png")
    c.on_toolbar_action("resize")
    assert _png(c).shape[1] == 250
    assert c.open_image_file(str(p))
    printed = []
    c.print_image = lambda img, dpi=96: (printed.append(1), True)[1]
    c.on_toolbar_action("print")
    assert printed == [1]
