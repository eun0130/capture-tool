"""Saving a capture hands it to the catalogue with where it came from and what kind of capture
it was; the read-ahead's text is reused; the search window opens from the bar and the tray."""
from pathlib import Path

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

    def add(self, path, img, meta, lines=None, ahead=None):
        if lines is None and ahead is not None:
            from capture_tool.app.indexer import Indexer
            if ahead[0] == Indexer.pixel_key(img):
                lines = ahead[1]
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


def test_CAPP_02b_the_gui_thread_never_hashes_the_picture(make, monkeypatch):
    """Comparing the saved pixels with the read-ahead's (31 ms at 4K) happens on the indexer."""
    from capture_tool.app.controller import Controller
    c = _with_indexer(make, ocr=FakeOcr(LINES))
    c.read_ahead_mode = "inline"
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    monkeypatch.setattr(Controller, "_read_key", staticmethod(lambda raw: (_ for _ in ()).throw(AssertionError("hashed on the GUI thread"))))
    c.on_toolbar_action("save")
    assert c.indexer.calls and c.indexer.calls[-1][3] is not None


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


def test_CAPP_07_the_search_button_opens_the_search_window_and_finds_look_alikes(make, tmp_path):
    from capture_tool.core.catalog import Catalog
    c = _with_indexer(make)
    c.catalog = Catalog(tmp_path / "catalog.db")
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (300, 250))
    c.on_toolbar_action("search_local")
    w = c.search_window
    assert w is not None and w.isVisible() and w.list.count() == 0
    assert c.session.state.name == "EDITING"                 # the capture stays open
    c.on_toolbar_action("search_similar")
    assert w._similar is not None and "비슷한" in w.status.text()
    c.cancel()
    c.catalog.close()


def test_CAPP_08_without_a_catalogue_the_search_says_so(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (300, 250))
    c.on_toolbar_action("search_local")
    assert c.search_window is None and "캡처 찾기" in c.messages[-1]


def test_CAPP_09_settings_and_hotkey_for_the_search(qt_app):
    from capture_tool.app.hotkeys import IDS
    from capture_tool.app.settings_dialog import ACTIONS, SettingsDialog
    assert "search" in IDS and ("search", "캡처 찾기") in ACTIONS
    d = SettingsDialog(Settings(catalog_text=False))
    assert d.catalog_enabled.isChecked() and not d.catalog_text.isChecked()
    d.catalog_enabled.setChecked(False)
    assert not d.catalog_text.isEnabled()
    s = d.result_settings()
    assert s.catalog_enabled is False and s.catalog_text is False


def test_CAPP_10_the_recent_strip_takes_thumbnails_from_the_catalogue(qt_app, tmp_path):
    from capture_tool.app.recent_strip import RecentStrip
    from capture_tool.core import tagging
    from PySide6.QtWidgets import QWidget
    img = np.full((120, 200, 3), 90, np.uint8)
    thumb = tagging.thumbnail(img)
    asked = []

    def source(p):
        asked.append(Path(p).name)
        return thumb if Path(p).name == "a.png" else None
    host = QWidget()
    strip = RecentStrip(host, sync=True, thumb_source=source)
    strip.set_paths([tmp_path / "a.png", tmp_path / "missing.png"])        # neither file exists
    assert asked == ["a.png", "missing.png"]
    assert not strip.buttons[0].icon().isNull() and strip.buttons[1].icon().isNull()


def test_CAPP_06_process_name_of_a_real_window():
    import ctypes
    from capture_tool.platform.windows import process_name
    tray = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    if not tray:
        pytest.skip("no taskbar window on this desktop")
    assert process_name(tray) == "explorer"
    assert process_name(0) == "" and process_name(123456789) == ""


class FakeShapeService:
    def __init__(self, present=False):
        self.present, self.unloaded = present, 0

    def available(self):
        return self.present

    def missing(self):
        return [] if self.present else ["clip-vit-b32-ml"]

    def image_blob(self, img):
        return b"\x00" * 1024

    def unload(self):
        self.unloaded += 1


def test_CAPP_11_shape_search_is_wired_through_the_controller(make, tmp_path, monkeypatch):
    from capture_tool.app.indexer import Indexer
    from capture_tool.core import model_store as ms
    from capture_tool.core.catalog import Catalog
    c = make(settings=Settings(auto_save=True, save_dir=str(tmp_path / "shots")))
    c.catalog = Catalog(tmp_path / "catalog.db")
    c.indexer = Indexer(c.catalog, None, lambda: str(tmp_path / "shots"), sync=True)
    fake = FakeShapeService(present=False)
    c.shape = fake
    assert c.indexer.embedder is None                                   # no pack: no vectors
    w = c.open_search()
    assert w.shape is fake and w.get_packs == c.get_shape_packs and not w.shape_btn.isHidden()
    got, prog, done = [], [], []

    def download(pack, root, progress=None, cancel=None):
        got.append((pack.id, root))
        progress(10 * 2**20, 227 * 2**20)
        fake.present = True
        return root / pack.id
    monkeypatch.setattr(ms, "download", download)
    c.get_shape_packs(["clip-vit-b32-ml"], done.append, lambda g, t: prog.append((g, t)))
    assert got[0][0] == "clip-vit-b32-ml" and got[0][1] == ms.user_root() and prog == [(10 * 2**20, 227 * 2**20)]
    assert done == [True] and c.indexer.embedder == fake.image_blob     # wired the moment it arrived
    monkeypatch.setattr(ms, "download", lambda *a, **k: (_ for _ in ()).throw(ms.DownloadError("no net")))
    done.clear()
    c.get_shape_packs(["clip-vit-b32-ml"], done.append, lambda g, t: None)
    assert done == [False] and "no net" in c.messages[-1]               # no AI window: said as a toast
    c.ai_idle()
    assert fake.unloaded == 1
    c.search_window.close()
    c.catalog.close()
