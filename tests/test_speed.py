"""v0.8.31 speed: the copy path and text mode do less on the GUI thread."""
import threading

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import DIB, PNG
from capture_tool.core.ocr import OcrLine
from tests.test_app import MON_A, MON_B, FakeOcr, FakeScreen, drag, make  # noqa: F401 (fixture)


def test_SPD_01_png_is_encoded_with_opencv_defaults(monkeypatch):
    """A compression parameter makes imencode 2.7x slower at 4K (the default already is level 1 + RLE)."""
    from capture_tool.app import controller as mod
    seen = []
    real = cv2.imencode

    def spy(ext, img, params=None):
        seen.append(params)
        return real(ext, img) if params is None else real(ext, img, params)
    monkeypatch.setattr(mod.cv2, "imencode", spy)
    p = mod.Controller._image_payload(np.full((20, 30, 3), 200, np.uint8), 144)
    assert PNG in p and DIB in p
    assert seen == [None]


def test_SPD_02_table_rows_are_found_on_the_worker_thread(make, qt_app):
    """After reading the text, the table search (a second OCR pass) ran in the worker - the capture
    stays responsive instead of freezing 0.5-0.9 s."""
    lines = [OcrLine("가 나", (100, 100, 60, 20), 0.9), OcrLine("다 라", (100, 140, 60, 20), 0.9)]
    c = make(ocr=FakeOcr(lines))
    c.sync = False
    threads = []
    orig = c._table_rows

    def spy(raw, ls, dpi=96):
        threads.append(threading.current_thread() is threading.main_thread())
        return orig(raw, ls, dpi)
    c._table_rows = spy
    c.start_capture()
    drag(c.overlays[0], (50, 50), (400, 300))
    c._start_text_mode()
    for _ in range(500):
        qt_app.processEvents()
        if c._text_lines:
            break
        QTest.qWait(10)
    assert c._text_lines and threads == [False]


def test_SPD_03_copy_hides_the_active_overlay_now_and_the_others_right_after(make, qt_app):
    """Each hidden full-screen window costs 16-55 ms; Enter → copied waits only for the one in front."""
    c = make(FakeScreen(cursor=(1000, 300), monitors=[MON_A, MON_B]))
    c.start_capture()
    front, back = c.overlays[0], c.overlays[1]
    drag(front, (10, 10), (110, 60))
    QTest.keyClick(front, Qt.Key_Return)
    assert PNG in c.clipboard.last
    assert front.isHidden() and not back.isHidden() and c.overlays == []
    qt_app.processEvents()
    assert back.isHidden()


def test_SPD_04_a_capture_started_before_the_deferred_hide_keeps_its_overlay(make, qt_app):
    c = make(FakeScreen(cursor=(1000, 300), monitors=[MON_A, MON_B]))
    c.start_capture()
    front = c.overlays[0]
    drag(front, (10, 10), (110, 60))
    QTest.keyClick(front, Qt.Key_Return)
    assert c.start_capture()                          # the next hotkey before the event loop ran
    back = [o for o in c.overlays if o.monitor is MON_A][0]
    assert not back.isHidden()
    qt_app.processEvents()
    assert not back.isHidden() and back.image.shape[0] > 8      # neither hidden nor released
