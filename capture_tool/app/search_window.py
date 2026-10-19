"""캡처 찾기: the saved captures searched by words (text, tags, app, title, file name), narrowed
by kind / content / app / period / colour, or by look (pictures like a given one). A found
capture opens with every capture button (double-click). Talks only to the catalogue, the
indexer and the two callbacks it is given."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QVBoxLayout, QWidget)

from ..core import tagging
from ..core.catalog import Catalog, Hit
from ..core.tagging import COLOURS, CONTENT, KINDS

ICON = QSize(176, 112)
DEBOUNCE_MS = 150
SIMILAR_DISTANCE = 24
PERIODS = [("전체 기간", None), ("오늘", 0), ("7일", 7), ("30일", 30), ("90일", 90)]
STYLE = """
QListWidget { background: #F4F5F8; }
QListWidget::item { padding: 6px; margin: 4px; border-radius: 8px; }
QListWidget::item:selected { background: #DCE8FF; color: #10203A; }
"""


def _since(days: int | None, now: datetime) -> str | None:
    if days is None:
        return None
    return (now - timedelta(days=days)).strftime("%Y-%m-%d") if days else now.strftime("%Y-%m-%d")


def _label(hit: Hit) -> str:
    when = hit.taken[:16].replace("T", " ") if hit.taken else ""
    kind = KINDS.get(hit.kind, hit.kind)
    extra = " · ".join(x for x in (when, hit.app, kind) if x)
    return hit.name + ("\n" + extra if extra else "")


class SearchWindow(QWidget):
    opened = Signal(str)

    def __init__(self, catalog: Catalog, indexer=None, open_path: Callable[[str], object] | None = None,
                 reveal: Callable[[Path], object] | None = None, sync: bool = False, parent=None):
        super().__init__(parent, Qt.Window)
        self.catalog, self.indexer = catalog, indexer
        self.open_path = open_path or (lambda p: None)
        self.reveal = reveal or (lambda p: None)
        self.sync = sync
        self.now = datetime.now
        self.ask_tags: Callable[[str], str | None] = self._ask_tags_dialog      # tests replace these
        self.ask_yes_no: Callable[[str, str], bool] = self._ask_yes_no_dialog
        self.pick_file: Callable[[], str | None] = self._pick_file_dialog
        self.copy_text: Callable[[str], object] = self._copy_text
        self._similar: int | None = None
        self._hits: list[Hit] = []
        self.setWindowTitle("캡처 찾기 — 저장한 캡처를 글자·태그·모양으로")
        self.resize(960, 640)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("찾을 말 — 캡처 속 글자 · 태그 · 앱 · 창 제목 · 파일 이름  (예: 매출, excel, 표, 빨강)")
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(self._query_changed)
        self.query.returnPressed.connect(self.open_current)
        top.addWidget(self.query, 1)
        self.similar_btn = QPushButton("비슷한 그림 찾기…")
        self.similar_btn.setToolTip("그림 파일을 고르면 그것과 닮은 캡처를 찾습니다. 창에 그림을 끌어다 놓아도 됩니다.")
        self.similar_btn.clicked.connect(self._pick_similar)
        top.addWidget(self.similar_btn)
        self.all_btn = QPushButton("모두 보기")
        self.all_btn.clicked.connect(self.show_all)
        top.addWidget(self.all_btn)
        v.addLayout(top)
        chips = QHBoxLayout()
        self.kind = self._combo(chips, "종류", [("모든 종류", None)] + [(label, key) for key, label in KINDS.items()])
        self.content = self._combo(chips, "내용", [("모든 내용", None)] + [(label, key) for key, label in CONTENT.items()])
        self.app = self._combo(chips, "앱", [("모든 앱", None)])
        self.period = self._combo(chips, "기간", PERIODS)
        self.colour = self._combo(chips, "색", [("모든 색", None)] + [(c, c) for c in COLOURS])
        chips.addStretch(1)
        v.addLayout(chips)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(ICON)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(lambda it: self._open(it))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        v.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        self.status = QLabel()
        bottom.addWidget(self.status, 1)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, fn in [("open", "열기", self.open_current), ("reveal", "폴더에서 보기", self.reveal_current),
                               ("tags", "태그 편집…", self.edit_tags), ("clear", "색인 지우기…", self.clear_index)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            bottom.addWidget(b)
            self.buttons[key] = b
        v.addLayout(bottom)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.run_search)
        if indexer is not None and hasattr(indexer, "changed"):
            indexer.changed.connect(self._changed)
            indexer.progress_changed.connect(self._progress)
        self._left = 0
        self.refresh()

    # --- building ----------------------------------------------------------------------------------
    def _combo(self, layout, title: str, items) -> QComboBox:
        box = QComboBox()
        box.setToolTip(title)
        for label, key in items:
            box.addItem(label, key)
        box.currentIndexChanged.connect(lambda _=0: self._query_changed())
        layout.addWidget(box)
        return box

    def refresh(self) -> None:
        """Apps may have appeared; the results may have changed."""
        current = self.app.currentData()
        self.app.blockSignals(True)
        self.app.clear()
        self.app.addItem("모든 앱", None)
        for a in self.catalog.apps():
            self.app.addItem(a, a)
        self.app.setCurrentIndex(max(0, self.app.findData(current)))
        self.app.blockSignals(False)
        self.run_search()

    # --- searching ---------------------------------------------------------------------------------
    def _query_changed(self, *_) -> None:
        if self.query.text().strip():
            self._similar = None                             # typing leaves the look-alike list
        if self.sync:
            self.run_search()
        else:
            self._timer.start(DEBOUNCE_MS)

    def filters(self) -> dict:
        return dict(kind=self.kind.currentData(), content=self.content.currentData(), app=self.app.currentData(),
                    since=_since(self.period.currentData(), self.now()), colour=self.colour.currentData())

    def run_search(self) -> None:
        if self._similar is not None:
            hits = self.catalog.similar(self._similar, limit=100, max_distance=SIMILAR_DISTANCE)
            f = self.filters()
            hits = [h for h in hits if (not f["kind"] or h.kind == f["kind"]) and (not f["content"] or h.content == f["content"])
                    and (not f["app"] or h.app == f["app"]) and (not f["since"] or h.taken >= f["since"])
                    and (not f["colour"] or f["colour"] in h.colors)]
            what = "비슷한 순"
        else:
            hits = self.catalog.search(self.query.text(), **self.filters())
            what = "새것부터" if not self.query.text().strip() else "잘 맞는 순"
        self._hits = hits
        self.list.clear()
        for h in hits:
            it = QListWidgetItem(_label(h))
            it.setData(Qt.UserRole, h.id)
            it.setToolTip(self._tooltip(h))
            it.setSizeHint(QSize(ICON.width() + 24, ICON.height() + 52))
            thumb = self.catalog.thumb(h.id)
            if thumb:
                pm = QPixmap()
                if pm.loadFromData(thumb):
                    it.setIcon(QIcon(pm))
            self.list.addItem(it)
        if hits:
            self.list.setCurrentRow(0)
        total = self.catalog.count()
        self._set_status(f"{len(hits)}개 ({what}) · 전체 {total}개")

    @staticmethod
    def _tooltip(h: Hit) -> str:
        parts = [h.path]
        if h.title:
            parts.append("창: " + h.title)
        if h.tags:
            parts.append("태그: " + ", ".join(h.tags))
        if h.snippet:
            parts.append(h.snippet)
        if h.distance >= 0:
            parts.append(f"차이 {h.distance}")
        return "\n".join(parts)

    def _set_status(self, text: str) -> None:
        if self._left:
            text += f" · 글자 읽는 중 {self._left}개 남음"
        self.status.setText(text)

    def results(self) -> list[Hit]:
        return list(self._hits)

    def current(self) -> Hit | None:
        it = self.list.currentItem()
        if it is None:
            return None
        fid = it.data(Qt.UserRole)
        return next((h for h in self._hits if h.id == fid), None)

    def show_all(self) -> None:
        self._similar = None
        self.query.blockSignals(True)
        self.query.clear()
        self.query.blockSignals(False)
        for box in (self.kind, self.content, self.app, self.period, self.colour):
            box.blockSignals(True)
            box.setCurrentIndex(0)
            box.blockSignals(False)
        self.run_search()

    def show_similar(self, picture) -> None:
        """Pictures like this one: a numpy image or a file path."""
        img = picture
        if not isinstance(picture, np.ndarray):
            try:
                img = cv2.imdecode(np.fromfile(str(picture), dtype=np.uint8), cv2.IMREAD_COLOR)
            except (OSError, ValueError, cv2.error):
                img = None
            if img is None or img.size == 0:
                self._set_status(f"'{Path(str(picture)).name}'은(는) 열 수 있는 그림이 아닙니다.")
                return
        self._similar = tagging.phash(img)
        self.query.blockSignals(True)
        self.query.clear()
        self.query.blockSignals(False)
        self.run_search()
        self.show()
        self.raise_()

    def _pick_similar(self) -> None:
        path = self.pick_file()
        if path:
            self.show_similar(path)

    # --- acting on a result ------------------------------------------------------------------------
    def _open(self, it) -> None:
        self.list.setCurrentItem(it)
        self.open_current()

    def open_current(self) -> None:
        h = self.current()
        if h is None:
            return
        self.opened.emit(h.path)
        self.open_path(h.path)

    def reveal_current(self) -> None:
        h = self.current()
        if h is not None:
            self.reveal(Path(h.path))

    def edit_tags(self) -> None:
        h = self.current()
        if h is None:
            return
        user = self.catalog.tags_of(h.id)["user"]
        text = self.ask_tags(", ".join(user))
        if text is None:
            return
        self.catalog.set_user_tags(h.id, [t.strip() for t in text.replace("，", ",").split(",") if t.strip()])
        self.run_search()

    def remove_current(self) -> None:
        h = self.current()
        if h is not None:
            self.catalog.remove(h.id)
            self.run_search()

    def clear_index(self) -> None:
        if not self.ask_yes_no("색인 지우기", "캡처 찾기의 색인(글자·태그·썸네일)을 지우고 저장 폴더를 처음부터 다시 읽습니다.\n"
                                        "그림 파일은 그대로 있습니다. 계속할까요?"):
            return
        self.catalog.clear()
        self.run_search()
        if self.indexer is not None:
            self.indexer.rescan()

    def _context_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        self.list.setCurrentItem(it)
        h = self.current()
        if h is None:
            return
        m = QMenu(self)
        m.addAction("열기 (모든 버튼으로 다시 쓰기)", self.open_current)
        m.addAction("폴더에서 보기", self.reveal_current)
        m.addAction("경로 복사", lambda: self.copy_text(h.path))
        m.addAction("이 그림과 비슷한 것 찾기", lambda: self.show_similar(h.path))
        m.addSeparator()
        m.addAction("태그 편집…", self.edit_tags)
        m.addAction("색인에서 빼기 (파일은 그대로)", self.remove_current)
        m.exec(self.list.mapToGlobal(pos))

    # --- the indexer's news ------------------------------------------------------------------------
    def _changed(self) -> None:
        if self.isVisible():
            if self.sync:
                self.refresh()
            else:
                self._timer.start(300)

    def _progress(self, left: int, total: int) -> None:
        self._left = left
        self._set_status(self.status.text().split(" · 글자 읽는 중")[0])

    # --- drops -------------------------------------------------------------------------------------
    def dragEnterEvent(self, e):
        from .recent_strip import image_paths
        if e.mimeData().hasUrls() and image_paths(e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        from .recent_strip import image_paths
        paths = image_paths(e.mimeData().urls())
        if paths:
            self.show_similar(paths[0])
            e.acceptProposedAction()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    # --- dialogs (replaced in tests) ----------------------------------------------------------------
    def _ask_tags_dialog(self, current: str) -> str | None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "태그 편집", "내 태그 (쉼표로 구분):", text=current)
        return text if ok else None

    def _ask_yes_no_dialog(self, title: str, text: str) -> bool:
        from .ai_ui import ask_yes_no
        return ask_yes_no(title, text, self)

    def _pick_file_dialog(self) -> str | None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "비슷한 그림 찾기 — 기준 그림", "",
                                              "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
        return path or None

    @staticmethod
    def _copy_text(text: str) -> None:
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
