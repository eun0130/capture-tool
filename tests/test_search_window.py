"""캡처 찾기 window: typing searches, chips narrow, a result opens the picture, look-alikes by
a picture, tag editing, dropping a file. Offscreen, a temp catalogue, no indexer thread."""
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt

from capture_tool.app.search_window import SearchWindow
from capture_tool.core import tagging
from capture_tool.core.catalog import Catalog
from capture_tool.core.tagging import CaptureMeta, Described


def pic(seed: int, w=320, h=200):
    img = np.full((h, w, 3), 255, np.uint8)
    rng = np.random.default_rng(seed)
    for _ in range(4):
        x, y = int(rng.integers(0, w - 60)), int(rng.integers(0, h - 40))
        cv2.rectangle(img, (x, y), (x + 60, y + 40), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


@pytest.fixture
def filled(tmp_path, qt_app):
    cat = Catalog(tmp_path / "catalog.db")
    folder = tmp_path / "shots"
    folder.mkdir()
    rows = [("a.png", 1, "window", "excel", "매출현황 - Excel", "2026-10-18T10:00:00", "3분기 매출현황 보고서", "table", ("흰색", "빨강")),
            ("b.png", 2, "area", "code", "main.py", "2026-10-19T10:00:00", "def total(rows): return 1", "code", ("파랑",)),
            ("c.jpg", 3, "scroll", "chrome", "Sales", "2026-10-20T10:00:00", "Sales report Q3", "photo", ("초록",))]
    ids = {}
    for name, seed, kind, app, title, taken, text, content, colors in rows:
        img = pic(seed)
        cv2.imwrite(str(folder / name), img)
        d = Described(320, 200, tagging.phash(img), colors, content, "piece")
        meta = CaptureMeta(kind, app, title, taken)
        ids[name] = cat.add(folder / name, d, meta, text=text, tags=tagging.auto_tags(meta, d), thumb=tagging.thumbnail(img))
    opened = []
    w = SearchWindow(cat, None, open_path=opened.append, reveal=lambda p: opened.append(("reveal", p)), sync=True)
    w.now = lambda: datetime(2026, 10, 20, 12, 0, 0)
    yield w, cat, folder, ids, opened
    w.close()
    cat.close()


def names(w):
    return [h.name for h in w.results()]


def test_SW_01_typing_searches_and_the_newest_come_first(filled):
    w, cat, folder, ids, opened = filled
    assert names(w) == ["c.jpg", "b.png", "a.png"] and w.list.count() == 3 and "3개" in w.status.text()
    assert not w.list.item(0).icon().isNull()                                 # thumbnails from the catalogue
    w.query.setText("출현황")
    assert names(w) == ["a.png"]
    w.query.setText("excel")
    assert names(w) == ["a.png"]
    w.query.setText("없는말")
    assert names(w) == [] and "0개" in w.status.text()
    w.query.setText("")
    assert len(names(w)) == 3


def test_SW_02_chips_narrow_the_list(filled):
    w, cat, folder, ids, opened = filled
    w.kind.setCurrentIndex(w.kind.findData("scroll"))
    assert names(w) == ["c.jpg"]
    w.kind.setCurrentIndex(0)
    w.content.setCurrentIndex(w.content.findData("code"))
    assert names(w) == ["b.png"]
    w.content.setCurrentIndex(0)
    assert [w.app.itemText(i) for i in range(w.app.count())] == ["모든 앱", "chrome", "code", "excel"]
    w.app.setCurrentIndex(w.app.findData("excel"))
    assert names(w) == ["a.png"]
    w.app.setCurrentIndex(0)
    w.period.setCurrentIndex(1)                                               # 오늘 (2026-10-20)
    assert names(w) == ["c.jpg"]
    w.period.setCurrentIndex(2)                                               # 7일
    assert names(w) == ["c.jpg", "b.png", "a.png"]
    w.period.setCurrentIndex(0)
    w.colour.setCurrentIndex(w.colour.findData("파랑"))
    assert names(w) == ["b.png"]
    w.show_all()
    assert len(names(w)) == 3 and w.colour.currentIndex() == 0


def test_SW_03_a_result_opens_the_picture_and_the_folder(filled):
    w, cat, folder, ids, opened = filled
    w.query.setText("sales")
    w.open_current()
    assert opened == [str(folder / "c.jpg")]
    w.list.itemActivated.emit(w.list.item(0))
    assert opened[-1] == str(folder / "c.jpg")
    w.reveal_current()
    assert opened[-1] == ("reveal", folder / "c.jpg")
    w.query.setText("없음")
    w.open_current()                                                          # nothing selected: nothing happens
    assert len(opened) == 3


def test_SW_04_look_alikes_by_a_picture_or_a_dropped_file(filled, tmp_path):
    w, cat, folder, ids, opened = filled
    w.show_similar(pic(2))                                                    # b's picture, slightly re-made
    assert names(w)[0] == "b.png" and w.results()[0].distance == 0
    assert "비슷한" in w.status.text()
    other = tmp_path / "query.png"
    cv2.imwrite(str(other), pic(3))
    w.pick_file = lambda: str(other)
    w.similar_btn.click()
    assert names(w)[0] == "c.jpg"
    w.query.setText("def")                                                    # typing leaves the look-alike list
    assert names(w) == ["b.png"] and w._similar is None
    w.show_similar(tmp_path / "missing.png")
    assert "열 수 있는 그림이 아닙니다" in w.status.text()


def test_SW_05_tags_are_edited_and_rows_removed(filled):
    w, cat, folder, ids, opened = filled
    w.query.setText("sales")
    w.ask_tags = lambda current: current + ", 중요, 분기보고"
    w.edit_tags()
    assert cat.tags_of(ids["c.jpg"])["user"] == ["중요", "분기보고"]
    w.query.setText("분기보고")
    assert names(w) == ["c.jpg"]
    w.ask_tags = lambda current: None                                         # cancelled: unchanged
    w.edit_tags()
    assert cat.tags_of(ids["c.jpg"])["user"] == ["중요", "분기보고"]
    w.remove_current()
    assert cat.count() == 2 and names(w) == []
    w.ask_yes_no = lambda t, x: False
    w.clear_index()
    assert cat.count() == 2
    w.ask_yes_no = lambda t, x: True
    w.clear_index()
    assert cat.count() == 0 and w.list.count() == 0


def test_SW_06_escape_closes_and_the_indexer_refreshes_it(tmp_path, qt_app):
    from PySide6.QtTest import QTest
    from capture_tool.app.indexer import Indexer
    cat = Catalog(tmp_path / "catalog.db")
    folder = tmp_path / "shots"
    folder.mkdir()
    ix = Indexer(cat, lambda img: [], lambda: str(folder), sync=True)
    w = SearchWindow(cat, ix, sync=True)
    w.show()
    assert w.list.count() == 0
    p = folder / "new.png"
    cv2.imwrite(str(p), pic(5))
    ix.add(p, pic(5), CaptureMeta("area"), [])
    assert w.list.count() == 1 and names(w) == ["new.png"]                   # changed → refreshed
    QTest.keyClick(w, Qt.Key_Escape)
    assert not w.isVisible()
    cat.close()
