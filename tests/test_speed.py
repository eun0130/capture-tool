"""v0.8.31 speed: the copy path and text mode do less on the GUI thread."""
import threading

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication, QThreadPool, Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import DIB, PNG
from capture_tool.core.ocr import OcrLine
from tests.test_app import MON_A, MON_B, FakeOcr, FakeScreen, drag, make  # noqa: F401 (fixture)


def test_SPD_13_the_catalogue_answers_in_under_50_ms_at_two_thousand_rows(tmp_path):
    """v0.9.0: 캡처 찾기 - FTS5 trigram for 3+ letters, LIKE for shorter, both over the one body column."""
    import time
    from capture_tool.core.catalog import Catalog, _colors_text
    cat = Catalog(tmp_path / "catalog.db")
    words = ["매출", "현황", "보고서", "분기", "회의", "설계", "sales", "report", "login", "excel"]
    with cat.db:
        for i in range(2000):
            text = " ".join(words[(i + k) % len(words)] for k in range(8)) + f" 항목{i}"
            cat.db.execute("INSERT INTO files (path, folder, name, kind, app, title, taken, phash, colors, content, text, text_done) "
                           "VALUES (?, 'D:/s', ?, 'area', 'excel', ?, ?, ?, ?, 'text', ?, 1)",
                           (f"D:/s/{i}.png", f"{i}.png", f"창 {i}", f"2026-{1 + i % 12:02d}-01T10:00:00", i, _colors_text(("흰색",)), text))
            cat.db.execute("INSERT INTO fts (rowid, body) VALUES (?, ?)", (i + 1, f"{i}.png excel 창 {i} " + text))
    for q in ("매출", "보고서 분기", "sales", "항목777", ""):
        t0 = time.perf_counter()
        hits = cat.search(q, limit=200)
        ms = (time.perf_counter() - t0) * 1000
        assert hits and ms < 50, (q, ms)
    t0 = time.perf_counter()
    cat.similar(12345)
    assert (time.perf_counter() - t0) * 1000 < 50
    cat.close()


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


def test_SPD_10_the_ink_box_of_a_tile_is_found_without_a_16_bit_copy():
    """Row and column ranges straight from uint8 reductions: the same box as the old int16
    per-channel version (63 ms per 4K tile), for 3-channel, 4-channel and grey tiles."""
    from capture_tool.core.ocr import _ink_box
    tile = np.full((1500, 1500, 3), 250, np.uint8)
    assert _ink_box(tile) is None                                 # blank paper
    tile[400:421, 700:711] = (20, 30, 40)                         # one word's worth of ink
    assert _ink_box(tile) == (338, 43, 736, 736)                  # padded, grown to the detector's minimum
    bgra = cv2.cvtColor(tile, cv2.COLOR_BGR2BGRA)                 # alpha 255 everywhere is not ink
    assert _ink_box(bgra) == (338, 43, 736, 736)
    grey = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    assert _ink_box(grey) == (338, 43, 736, 736)
    faint = np.full((800, 800, 3), 250, np.uint8)
    faint[100:200, 100:200] = 230                                 # contrast 20 < 24: still blank
    assert _ink_box(faint) is None
    big = np.full((1000, 2000, 3), 255, np.uint8)
    big[10:990, 10:1990, 1] = 0                                   # ink everywhere: the whole tile
    assert _ink_box(big) == (0, 0, 2000, 1000)


def test_SPD_11_the_photo_check_counts_colours_without_sorting_pixel_rows():
    """np.unique over rows of 3 bytes costs 50-70 ms per recognize; the same verdict comes from
    packed 24-bit keys."""
    from capture_tool.core.ocr import looks_like_photo
    rng = np.random.default_rng(3)
    shot = np.full((1080, 1920, 3), 255, np.uint8)
    shot[100:900, 200:1700] = rng.integers(0, 255, (800, 1500, 3), np.uint8)
    assert not looks_like_photo(shot)                             # white covers > 12 %
    photo = rng.integers(0, 255, (1200, 1600, 3), np.uint8)
    assert looks_like_photo(photo)
    few = (rng.integers(0, 4, (600, 800, 3)) * 60).astype(np.uint8)
    assert not looks_like_photo(few)                              # 64 colours only: a drawing
    assert not looks_like_photo(cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY))


def test_SPD_12_the_live_copy_encodes_off_the_gui_thread_and_only_the_newest_round_lands(make, qt_app):
    """While drawing, the clipboard copy (PNG + DIB: 50-70 ms for a big area) was built on the GUI
    thread 300 ms after each stroke. It runs in the worker now; a result from an older round, or
    one arriving after the capture ended, is dropped."""
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))                    # sync: the first copy lands at once
    pngs = lambda: [p[PNG] for p in c.clipboard.payloads if PNG in p]   # noqa: E731
    n = len(pngs())
    c.sync = False
    threads = []
    real = c._image_payload

    def spy(img, dpi=96):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(img, dpi)
    c._image_payload = spy
    ov.set_tool("rect")
    drag(ov, (150, 150), (300, 300))                    # starts the 300 ms timer
    c._auto_copy()                                       # what the timer calls
    assert len(pngs()) == n                              # nothing built on the GUI thread
    assert QThreadPool.globalInstance().waitForDone(10000)
    QCoreApplication.sendPostedEvents(c)                 # the worker's result, delivered to the controller only
    assert len(pngs()) == n + 1 and threads == [False]
    c._on_auto_ready((c._auto_seq - 1, {PNG: b"old"}))  # an older round: the area changed meanwhile
    assert pngs()[-1] != b"old"
    seq = c._auto_seq + 1
    c._auto_seq = seq
    QTest.keyClick(ov, Qt.Key_Escape)
    QTest.keyClick(ov, Qt.Key_Escape)                    # the capture ends while a round is in flight
    c._on_auto_ready((seq, {PNG: b"late"}))
    assert pngs()[-1] != b"late"
    c.sync = True


def test_SPD_14_nearest_by_shape_answers_in_under_60_ms_at_ten_thousand_rows(tmp_path):
    """v0.9.1: 모양으로 찾기 - every stored vector is read and dotted with the query in numpy."""
    import time
    from capture_tool.core.catalog import Catalog
    from capture_tool.core.shape import to_blob
    cat = Catalog(tmp_path / "catalog.db")
    rng = np.random.default_rng(0)
    vecs = rng.standard_normal((10_000, 512)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    with cat.db:
        for i in range(10_000):
            cat.db.execute("INSERT INTO files (path, folder, name, kind, taken, embed) VALUES (?, 'D:/s', ?, 'area', ?, ?)",
                           (f"D:/s/{i}.png", f"{i}.png", "2026-10-01T10:00:00", to_blob(vecs[i])))
    q = vecs[1234]
    t0 = time.perf_counter()
    hits = cat.nearest(q, limit=60, min_score=0.17)
    ms = (time.perf_counter() - t0) * 1000
    assert hits and hits[0].id == 1235 and hits[0].score > 0.99 and ms < 60, ms
    t0 = time.perf_counter()
    hits = cat.nearest(q, limit=60, min_score=0.08, kind="area", since="2026-09-01", centre=True)
    assert hits[0].id == 1235 and (time.perf_counter() - t0) * 1000 < 100
    cat.close()
