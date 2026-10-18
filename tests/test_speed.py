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
    from PySide6.QtCore import QThreadPool
    assert QThreadPool.globalInstance().waitForDone(10000)    # the worker ran; no event loop in the offscreen
    assert threads == [False] and c._table_job is not None    # suite (a shown overlay + processEvents leaks
    c.sync = True                                              # hover state into later tests)


def test_SPD_03_copy_hides_the_active_overlay_now_and_the_others_right_after(make, qt_app):
    """Each hidden full-screen window costs 16-55 ms; Enter → copied waits only for the one in front."""
    c = make(FakeScreen(cursor=(1000, 300), monitors=[MON_A, MON_B]))
    c.start_capture()
    front, back = c.overlays[0], c.overlays[1]
    drag(front, (10, 10), (110, 60))
    QTest.keyClick(front, Qt.Key_Return)
    assert PNG in c.clipboard.last
    assert front.isHidden() and not back.isHidden() and c.overlays == []
    c._hide_rest()                                             # what the 0 ms timer calls next turn
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
    c._hide_rest()
    assert not back.isHidden() and back.image.shape[0] > 8      # neither hidden nor released


def test_SPD_05_dimmed_screen_is_cached_and_the_hole_shows_the_live_pixels(make, qt_app):
    """paintEvent at 4K took 17.7 ms per frame (a path fill over the whole screen each move): the dimmed
    frame is made once per capture and only the selection is drawn on top - pixels stay identical."""
    from capture_tool.core.geometry import Monitor, Rect
    big = Monitor(0, Rect(0, 0, 1200, 900), 1.5, True, "HiDPI")
    img = np.full((900, 1200, 3), 255, np.uint8)
    img[300:600, 300:600] = (0, 0, 255)                       # a red block (BGR) in the middle
    c = make(screen=FakeScreen(monitors=[big], image=img))
    c.start_capture()
    ov = c.overlays[0]
    assert ov._dim_cache is None                               # nothing built before the first paint
    drag(ov, (250, 250), (350, 350))                           # logical: physical 375..525 - inside the block
    shot = ov.grab().toImage()
    inside, outside = shot.pixelColor(300, 300), shot.pixelColor(100, 100)
    assert (inside.red(), inside.green(), inside.blue()) == (255, 0, 0)           # live pixels in the hole
    assert outside.red() < 200 and outside.red() == outside.green() == outside.blue() or outside.red() < 200
    assert ov._dim_cache is not None
    first = ov._dim_cache
    ov.grab()                                                  # a second paint (no event loop: a shown overlay
    assert ov._dim_cache is first                              # plus processEvents leaks hover state to later tests)
    c.close_overlays()
    assert ov._dim_cache is None                               # dropped with the frame (memory)


def test_SPD_06_the_veil_is_a_plain_image_blend_never_a_painted_pixmap():
    """A QPixmap that a QPainter has drawn on carries a raster paint engine; freed by the garbage
    collector on the OCR warm-up thread it crashed the whole process (full suite, twice at the same
    test). The veil is computed on the numpy image instead and matches what fillRect(DIM) gives."""
    from capture_tool.app.render import dim_image
    img = np.zeros((2, 3, 3), np.uint8)
    img[0, 0] = (255, 255, 255)
    img[0, 1] = (0, 0, 0)
    out = dim_image(img)
    a = 140 / 255
    assert tuple(out[0, 0]) == tuple(int(round(255 * (1 - a) + c * a)) for c in (24, 18, 15))
    assert tuple(out[0, 1]) == tuple(int(round(c * a)) for c in (24, 18, 15))
    assert out.shape == img.shape and out.dtype == np.uint8
    assert dim_image(np.full((2, 2), 200, np.uint8)).shape == (2, 2, 3)      # grey frames too


def test_SPD_07_a_deferred_hide_after_close_all_touches_no_deleted_window(make, qt_app):
    """close_all (tests' teardown, the app's quit) deletes the pooled overlays; the hide that a copy
    deferred must then do nothing instead of calling into a deleted window."""
    c = make(FakeScreen(cursor=(1000, 300), monitors=[MON_A, MON_B]))
    c.start_capture()
    front = c.overlays[0]
    drag(front, (10, 10), (110, 60))
    QTest.keyClick(front, Qt.Key_Return)
    back = [o for o in c._pool.values() if o.monitor is MON_A][0]
    assert c._later == [back]
    c._pool.clear()                                   # what close_all does before deleteLater
    c._hide_rest()                                    # what the timer will call: skipped, no call into it
    assert c._later == [] and not back.isHidden()


def test_SPD_08_opencv_keeps_a_small_thread_pool():
    """The first big OpenCV op (the 4K veil) started one worker per core - 31 idle threads for the
    app's lifetime on a 32-core PC (RES_05: 87 threads). The render module caps the pool."""
    import capture_tool.app.render  # noqa: F401 - the cap is set when the module loads
    assert 1 <= cv2.getNumThreads() <= 4


def test_SPD_09_the_ocr_warm_up_thread_never_runs_a_garbage_collection():
    """Four crashes in the full suite had the same shape: "Garbage-collecting" on the ocr-warmup thread
    while it imports the reader - the collection freed Qt windows left in reference cycles, whose
    C++ side must die on the GUI thread (BUG-119). The collector is paused for the thread's life."""
    import gc
    from capture_tool.core.ocr import OcrEngine
    seen = []

    def note(phase, info):
        if phase == "start":
            seen.append(threading.current_thread().name)
    gc.callbacks.append(note)
    try:
        def factory():
            junk = [[i] for i in range(300000)]        # plenty of tracked containers: would collect
            return object()
        OcrEngine(factory=factory).warmup().join(30)
    finally:
        gc.callbacks.remove(note)
    assert "ocr-warmup" not in seen
    assert gc.isenabled()
