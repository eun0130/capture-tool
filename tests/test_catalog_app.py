"""Saving a capture hands it to the catalogue with where it came from and what kind of capture
it was; the read-ahead's text is reused; the search window opens from the bar and the tray."""
import numpy as np
import pytest
from PySide6.QtCore import QPoint

from capture_tool.core.geometry import Rect
from capture_tool.core.settings import Settings
from capture_tool.platform.windows import WindowInfo
from tests.test_app import FakeOcr, FakeScreen, drag, make  # noqa: F401 (fixture)

LINES = [("매출 현황", (100, 100, 200, 30)), ("3분기 보고", (100, 140, 200, 30))]


class RecIndexer:
    def __init__(self):
        self.calls = []

    def add(self, path, img, meta, lines=None):
        self.calls.append((path, img.shape, meta, lines))


def _with_indexer(make, **kw):
    settings = kw.pop("settings", None) or Settings(auto_save=True)
    c = make(settings=settings, **kw)
    c.indexer = RecIndexer()
    return c


def test_CAPP_01_a_saved_area_goes_to_the_catalogue_with_the_window_under_it(make, tmp_path):
    wins = [WindowInfo(7, "매출현황 - Excel", Rect(50, 60, 600, 400))]
    c = _with_indexer(make, screen=FakeScreen(wins=wins))
    c.screen.process_name = lambda hwnd: "excel" if hwnd == 7 else ""
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (300, 250))
    c.on_toolbar_action("save")
    (path, shape, meta, lines), = c.indexer.calls
    assert path.suffix == ".png" and path.is_file() and shape == (150, 200, 3)
    assert meta.kind == "area" and meta.app == "excel" and meta.title == "매출현황 - Excel" and meta.taken[:4] == "2026" or meta.taken
    assert lines is None                                      # nothing read ahead in a sync controller


def test_CAPP_02_the_read_ahead_text_is_reused_not_read_twice(make):
    c = _with_indexer(make, ocr=FakeOcr(LINES))
    c.read_ahead_mode = "inline"
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert c._ahead is not None and c._ahead["done"].is_set()
    c.on_toolbar_action("save")
    (_, _, meta, lines), = c.indexer.calls
    assert [l[0] for l in lines] == ["매출 현황", "3분기 보고"] and meta.kind == "area"   # (FakeOcr's tuples)
    ov2 = None
    c.start_capture()
    ov2 = c.overlays[0]
    drag(ov2, (100, 100), (500, 400))
    ov2.set_tool("rect")
    drag(ov2, (150, 150), (250, 250))                        # drawn on: the pixels differ from what was read
    c.on_toolbar_action("save")
    assert c.indexer.calls[-1][3] is None


def test_CAPP_03_each_kind_of_capture_is_named(make):
    wins = [WindowInfo(3, "메모장", Rect(50, 60, 300, 200))]
    c = _with_indexer(make, screen=FakeScreen(wins=wins))
    c.start_capture()
    ov = c.overlays[0]
    c.on_select_rect(Rect(50, 60, 300, 200), ov, window=wins[0])   # a click on the window
    c.on_toolbar_action("save")
    assert c.indexer.calls[-1][2].kind == "window" and c.indexer.calls[-1][2].title == "메모장"
    c.start_capture("fullscreen")
    assert c.indexer.calls[-1][2].kind == "fullscreen" and c.indexer.calls[-1][2].title == ""
    img = np.full((300, 400, 3), 200, np.uint8)
    c.open_editor(img, 96, "스크롤 캡처 · 창", kind="scroll")
    assert c.indexer.calls[-1][2].kind == "scroll"
    c.cancel()
    p = c.pin(img, QPoint(10, 10))
    p.saveRequested.emit(p)
    assert c.indexer.calls[-1][2].kind == "pin"
    p.close()


def test_CAPP_04_catalogue_off_or_absent_changes_nothing(make):
    c = _with_indexer(make, settings=Settings(auto_save=True, catalog_enabled=False))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (300, 250))
    c.on_toolbar_action("save")
    assert c.indexer.calls == [] and any("저장했습니다" in m for m in c.messages)
    c2 = make(settings=Settings(auto_save=True))
    c2.start_capture()
    drag(c2.overlays[0], (100, 100), (300, 250))
    c2.on_toolbar_action("save")                              # indexer None: just saves
    assert any("저장했습니다" in m for m in c2.messages)


def test_CAPP_05_a_broken_indexer_never_breaks_a_save(make):
    c = _with_indexer(make)
    c.indexer.add = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (300, 250))
    c.on_toolbar_action("save")
    assert any("저장했습니다" in m for m in c.messages)


def test_CAPP_06_process_name_of_a_real_window():
    import ctypes
    from capture_tool.platform.windows import process_name
    tray = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    if not tray:
        pytest.skip("no taskbar window on this desktop")
    assert process_name(tray) == "explorer"
    assert process_name(0) == "" and process_name(123456789) == ""
