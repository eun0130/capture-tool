"""The indexer feeds the catalogue off the GUI thread: a saved capture is described at once, its
text comes from the read-ahead or later when idle, the folder backlog is worked through."""
import cv2
import numpy as np
import pytest

from capture_tool.app.indexer import Indexer
from capture_tool.core.catalog import Catalog
from capture_tool.core.ocr import OcrLine
from capture_tool.core.tagging import CaptureMeta


def picture(text="Sales"):
    img = np.full((200, 400, 3), 255, np.uint8)
    cv2.putText(img, text, (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    return img


class FakeReader:
    def __init__(self, text="매출 보고서 2026"):
        self.text, self.calls = text, []

    def __call__(self, img):
        self.calls.append(img.shape)
        return [OcrLine(self.text, (20, 80, 300, 50), 0.9)]


@pytest.fixture
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    yield c
    c.close()


def test_IDX_01_a_saved_capture_is_described_at_once_and_read_with_the_read_ahead_or_later(cat, tmp_path, qt_app):
    folder = tmp_path / "shots"
    folder.mkdir()
    reader = FakeReader()
    busy = {"v": False}
    ix = Indexer(cat, reader, lambda: str(folder), busy=lambda: busy["v"], sync=True)
    changes = []
    ix.changed.connect(lambda: changes.append(1))
    p = folder / "one.png"
    cv2.imwrite(str(p), picture())
    lines = [OcrLine("읽어 둔 글 010-1111-2222", (0, 0, 100, 20), 0.9)]
    ix.add(p, picture(), CaptureMeta("window", "excel", "매출 - Excel", "2026-10-20T10:00:00"), lines)
    hit = cat.search("읽어")[0]
    assert hit.path == str(p) and hit.kind == "window" and hit.app == "excel" and hit.text_done == 1
    assert "2222" not in hit.snippet and reader.calls == [] and changes == [1]      # the read-ahead was reused
    assert cat.thumb(hit.id) and "창" in hit.tags and "excel" in hit.tags and "읽어" in hit.tags
    p2 = folder / "two.png"
    cv2.imwrite(str(p2), picture("Other"))
    same = picture("Other")
    ix.add(p2, same, CaptureMeta("area"), None, ahead=(Indexer.pixel_key(same), lines))   # the read-ahead's pixels
    assert reader.calls == [] and cat.search("읽어")[1].path == str(p2)
    p3 = folder / "three.png"
    cv2.imwrite(str(p3), picture("Third"))
    ix.add(p3, picture("Third"), CaptureMeta("area"), None, ahead=(Indexer.pixel_key(same), lines))  # other pixels
    assert reader.calls == [(200, 400, 3)] and cat.search("보고서")[0].path == str(p3)
    assert cat.get(cat.search("보고서")[0].id).text_done == 1 and "매출" in cat.get(3).tags


def test_IDX_02_rescan_catalogues_the_folder_backlog_and_waits_while_capturing(cat, tmp_path, qt_app):
    folder = tmp_path / "shots"
    folder.mkdir()
    for name in ("a.png", "b.jpg"):
        cv2.imwrite(str(folder / name), picture(name))
    (folder / "note.txt").write_text("not a picture", encoding="utf-8")
    (folder / "broken.png").write_bytes(b"not really a png")
    reader = FakeReader("backlog text")
    ix = Indexer(cat, reader, lambda: str(folder), sync=True)
    progress = []
    ix.progress_changed.connect(lambda left, total: progress.append((left, total)))
    ix.rescan()
    assert cat.count() == 2 and len(reader.calls) == 2                              # broken.png skipped, txt ignored
    assert {h.name for h in cat.search("backlog")} == {"a.png", "b.jpg"}
    assert all(h.kind == "file" and h.taken for h in cat.search(""))
    assert progress[-1] == (0, 2) and cat.pending() == []
    ix.rescan()                                                                       # nothing new: nothing read again
    assert len(reader.calls) == 2
    (folder / "a.png").unlink()
    ix.rescan()
    assert cat.count() == 1
    ix2 = Indexer(cat, reader, lambda: str(folder), text_enabled=lambda: False, sync=True)
    cv2.imwrite(str(folder / "c.png"), picture("c"))
    ix2.rescan()
    assert cat.count() == 2 and len(reader.calls) == 2 and cat.pending_count() == 1  # text off: described, not read


def test_IDX_03_an_unreadable_picture_is_marked_and_the_rest_goes_on(cat, tmp_path, qt_app):
    folder = tmp_path / "shots"
    folder.mkdir()
    cv2.imwrite(str(folder / "ok.png"), picture())
    cv2.imwrite(str(folder / "bad.png"), picture("bad"))

    calls = []

    def read(img):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("reader broke")
        return [OcrLine("fine", (0, 0, 10, 10), 0.9)]
    ix = Indexer(cat, read, lambda: str(folder), sync=True)
    ix.rescan()
    rows = {h.name: h.text_done for h in cat.search("")}
    assert sorted(rows.values()) == [-1, 1] and cat.pending() == []


def test_IDX_04_the_thread_mode_runs_jobs_in_order_and_signals_on_the_gui_thread(cat, tmp_path, qt_app):
    from PySide6.QtTest import QTest
    folder = tmp_path / "shots"
    folder.mkdir()
    reader = FakeReader("threaded")
    ix = Indexer(cat, reader, lambda: str(folder))
    got = []
    ix.changed.connect(lambda: got.append(1))
    p = folder / "t.png"
    cv2.imwrite(str(p), picture())
    ix.add(p, picture(), CaptureMeta("area"), None)
    for _ in range(100):
        QTest.qWait(20)
        if cat.pending_count() == 0 and cat.count() == 1:
            break
    assert cat.search("threaded")[0].path == str(p)
    QTest.qWait(50)
    assert got                                                                        # queued signal delivered here
    ix.stop()
