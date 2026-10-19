"""Fills the catalogue behind 캡처 찾기 off the GUI thread: every saved capture is described
(hash, colours, kind, tags, thumbnail) the moment it is saved, its text comes from the read-ahead
when that already read the same pixels, else it is read later when the app is idle - as is the
backlog of pictures that were in the save folder before. One worker thread, one queue."""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core import tagging
from ..core.catalog import Catalog
from ..core.tagging import CaptureMeta

log = logging.getLogger(__name__)
IDLE_WAIT_S = 0.5            # how often the worker looks again while the person is capturing
MAX_PIXELS = 60_000_000


def _load(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except (OSError, cv2.error, ValueError):
        return None
    if img is None or img.size == 0 or img.shape[0] * img.shape[1] > MAX_PIXELS:
        return None
    return np.ascontiguousarray(img[:, :, :3])


class Indexer(QObject):
    changed = Signal()                     # the catalogue's content changed (a search window refreshes)
    progress_changed = Signal(int, int)    # (left to read, total pending at the start of this run)

    def __init__(self, catalog: Catalog, read_text: Callable[[np.ndarray], list] | None,
                 folder: Callable[[], str | None], busy: Callable[[], bool] = lambda: False,
                 text_enabled: Callable[[], bool] = lambda: True, sync: bool = False, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.read_text = read_text
        self.folder = folder
        self.busy = busy
        self.text_enabled = text_enabled
        self.sync = sync
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = False
        self.pending_total = 0
        self.ocr_calls = 0

    # --- what the app asks ---------------------------------------------------------------------
    def add(self, path: str | Path, img: np.ndarray, meta: CaptureMeta, lines: list | None = None) -> None:
        """A capture was just saved. Described now (ms); its text now if `lines` were read
        already, else later when idle."""
        self._run(lambda: self._add(str(path), img, meta, lines))

    def rescan(self) -> None:
        """Compare the catalogue with the save folder: new pictures are added (text later),
        changed ones described again, gone ones dropped."""
        self._run(self._rescan)

    def run_backlog(self) -> None:
        """Read the text of catalogued pictures that haven't got it yet (sync: all of it now)."""
        self._run(self._backlog)

    def stop(self) -> None:
        self._stop = True

    # --- the worker ----------------------------------------------------------------------------
    def _run(self, job: Callable[[], None]) -> None:
        if self.sync:
            job()
            return
        self._queue.put(job)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="catalog-indexer", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop:
            try:
                job = self._queue.get(timeout=30)
            except queue.Empty:
                return
            try:
                job()
            except Exception:  # noqa: BLE001 - the catalogue must never take the app down
                log.exception("catalogue job failed")

    def _wait_idle(self) -> bool:
        """True once the app is idle; False if asked to stop meanwhile."""
        while self.busy() and not self._stop and not self.sync:
            time.sleep(IDLE_WAIT_S)
        return not self._stop

    # --- the jobs ------------------------------------------------------------------------------
    def _text_of(self, lines: list | None) -> str | None:
        if lines is None:
            return None
        return "\n".join(l.text for l in lines if getattr(l, "text", "").strip())

    def _add(self, path: str, img: np.ndarray, meta: CaptureMeta, lines: list | None) -> None:
        d = tagging.describe(img, lines)
        want_text = self.text_enabled() and self.read_text is not None
        text = self._text_of(lines) if want_text else ""
        tags = tagging.auto_tags(meta, d, lines)
        self.catalog.add(path, d, meta, text=text, tags=tags, thumb=tagging.thumbnail(img))
        self.changed.emit()
        if want_text and lines is None:
            self._backlog()

    def _rescan(self) -> None:
        folder = self.folder()
        if not folder:
            return
        new, removed, moved = self.catalog.reconcile(folder)
        for path in new:
            if not self._wait_idle():
                return
            img = _load(path)
            if img is None:
                continue
            taken = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(Path(path).stat().st_mtime))
            meta = CaptureMeta("file", "", "", taken)
            d = tagging.describe(img)
            self.catalog.add(path, d, meta, text=None, tags=tagging.auto_tags(meta, d), thumb=tagging.thumbnail(img))
        if new or removed or moved:
            self.changed.emit()
        self._backlog()

    def _backlog(self) -> None:
        if not (self.text_enabled() and self.read_text is not None):
            return
        total = self.catalog.pending_count()
        self.pending_total = total
        done = 0
        while True:
            if not self._wait_idle():
                return
            batch = self.catalog.pending(limit=5)
            if not batch:
                break
            for fid, path in batch:
                if not self._wait_idle():
                    return
                img = _load(path)
                if img is None:
                    self.catalog.mark_failed(fid)
                    continue
                try:
                    self.ocr_calls += 1
                    lines = list(self.read_text(img))
                except Exception:  # noqa: BLE001 - one unreadable picture must not stop the rest
                    log.exception("catalogue: reading %s failed", path)
                    self.catalog.mark_failed(fid)
                    continue
                self.catalog.set_text(fid, self._text_of(lines) or "", tagging.keywords(lines, 5))
                done += 1
                self.progress_changed.emit(max(0, total - done), total)
        self.progress_changed.emit(0, total)
        if done:
            self.changed.emit()
