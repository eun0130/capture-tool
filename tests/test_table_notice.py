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
