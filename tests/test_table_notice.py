"""도형PPT with a ruled table: sent straight to PowerPoint the table is a real PowerPoint table, on
the clipboard it is cell boxes (the clipboard format can't hold tables). The person is told which
one they got, right away, and the clipboard always ends up with the complete capture."""
import io
import zipfile

import cv2
import numpy as np

from capture_tool.core.clipboard_payload import GVML
from capture_tool.core.shapes import recognize_layout
from tests.test_app import FakePpt, make  # noqa: F401 (fixture)


def _table_det():
    img = np.full((220, 420, 3), 255, np.uint8)
    g = (180, 180, 180)
    cv2.rectangle(img, (20, 20), (380, 160), g, 1)
    for y in (60, 110):
        cv2.line(img, (20, y), (380, y), g, 1)
    for x in (140, 260):
        cv2.line(img, (x, 20), (x, 160), g, 1)
    cv2.rectangle(img, (20, 180), (120, 210), (162, 73, 28), -1)          # a button next to it
    return img, recognize_layout(img, [], None, 96)


def _shapes_on_clipboard(c) -> int:
    z = zipfile.ZipFile(io.BytesIO(c.clipboard.last[GVML]))
    xml = z.read("clipboard/drawings/drawing1.xml").decode()
    return xml.count("<a:sp>")


def test_TNOTE_01_sent_to_powerpoint_says_real_table_and_clipboard_differs(make):
    c = make()
    c.powerpoint = FakePpt()
    img, det = _table_det()
    c._finish_shapes(det, [], img, None, send=True, dpi=96)
    item = c.powerpoint.items[-1]
    assert len(item.tables) == 1
    msg = c.messages[-1]
    assert "PowerPoint 표" in msg and "Ctrl+V" in msg and "칸 상자" in msg, msg
    assert _shapes_on_clipboard(c) >= 9 + 1                 # clipboard: all 9 cells as boxes + the button


def test_TNOTE_02_copy_only_says_cells_are_boxes(make):
    c = make()
    img, det = _table_det()
    c._finish_shapes(det, [], img, None, send=False, dpi=96)
    msg = c.messages[-1]
    assert "칸 상자" in msg and "PowerPoint 표" in msg, msg
    assert _shapes_on_clipboard(c) >= 10


def test_TNOTE_03_no_table_no_extra_words(make):
    c = make()
    c.powerpoint = FakePpt()
    img = np.full((120, 300, 3), 255, np.uint8)
    cv2.rectangle(img, (20, 20), (140, 90), (162, 73, 28), -1)
    det = recognize_layout(img, [], None, 96)
    c._finish_shapes(det, [], img, None, send=True, dpi=96)
    assert "칸 상자" not in c.messages[-1]


def test_TNOTE_04_powerpoint_failed_still_complete_on_clipboard(make):
    c = make()
    c.powerpoint = FakePpt(ok=False)
    img, det = _table_det()
    c._finish_shapes(det, [], img, None, send=True, dpi=96)
    assert "칸 상자" in c.messages[-1], c.messages[-1]
    assert _shapes_on_clipboard(c) >= 10


def test_TNOTE_05_table_done_closes_the_capture(make):
    """User (v0.8.1): after choosing 'PPT에 넣기' nothing seemed to happen - the capture stayed over
    PowerPoint until Esc. Once the table is delivered the capture closes, like the PPT picture."""
    from tests.test_app import drag
    from capture_tool.core.table_capture import CapturedTable
    for target in ("ppt", "excel", "word"):
        c = make()
        c.powerpoint = FakePpt()
        c.word = type("W", (), {"insert": lambda self, col_widths=None: 1, "busy": False})()
        c.settings.table_quick, c.settings.table_target = True, target
        c.start_capture()
        drag(c.overlays[0], (100, 100), (400, 300))
        t = CapturedTable([["a", "b"], ["c", "d"]], (0, 0, 10, 10))
        c._pending = ([], None, None, 96)
        c._on_job_done(("table", [object()], None, None, t))
        assert c.overlays == [], target
        assert c.messages and ("표 2행×2열" in c.messages[-1] or "넣는 중" in c.messages[-1]), c.messages[-1:]


def test_TNOTE_06_shapes_ppt_on_a_table_capture_sends_a_table(make):
    """User (v0.8.1): 도형PPT on a line-drawn table gave scattered white text boxes (hard to see)."""
    import cv2 as _cv2
    from pathlib import Path as _P
    from capture_tool.core.ocr import OcrEngine
    from capture_tool.platform.powerpoint import TableItem
    c = make(ocr=OcrEngine())
    c.powerpoint = FakePpt()
    img = _cv2.imread(str(_P(__file__).parent / "data" / "terminal_small_table.png"))
    c._run_recognition_on(img, "ppt", 96)
    item = c.powerpoint.items[-1]
    assert isinstance(item, TableItem) and len(item.rows) == 5, item


def test_TNOTE_07_table_with_drawings_goes_as_table_plus_marks(make):
    """User (v0.8.5): 도형PPT on a table with numbered marks drawn on it fell apart into loose,
    see-through text. Now: the table as a PowerPoint table, the marks as shapes on top."""
    import cv2 as _cv2
    from pathlib import Path as _P
    from capture_tool.core.annotations import Shape
    from capture_tool.core.ocr import OcrEngine
    from capture_tool.platform.powerpoint import ClipboardShapes
    c = make(ocr=OcrEngine())
    c.powerpoint = FakePpt()
    img = _cv2.imread(str(_P(__file__).parent / "data" / "terminal_metrics_table.png"))
    marks = [Shape("step", [(470, 90)], number=1), Shape("rect", [(430, 40), (760, 270)], color="#F76707")]
    c._pending = ([], img, None, 96)
    c._run_recognition_on(img, "ppt", 96, final=img, user_shapes=marks)
    item = c.powerpoint.items[-1]
    assert isinstance(item, ClipboardShapes) and len(item.tables) == 1, item
    t = item.tables[0]
    assert (t.rows, t.cols) == (5, 3) and t.cells[0].fill                     # the dark table, as a table
    assert "표 5행×3열과 그려 넣은 표시" in c.messages[-1], c.messages[-1]


def test_TNOTE_08_dark_page_gets_its_panel_behind_the_shapes():
    """User (v0.8.5): white text from a dark screen came out on a see-through slide."""
    import numpy as _np
    from capture_tool.core.shapes import page_panel
    dark = _np.full((60, 80, 3), 30, _np.uint8)
    p = page_panel(dark)
    assert p is not None and (p.w, p.h) == (80, 60) and p.fill.upper() == "#1E1E1E" and p.stroke is None
    assert page_panel(_np.full((60, 80, 3), 255, _np.uint8)) is None
    assert page_panel(dark, keep_style=False) is None
