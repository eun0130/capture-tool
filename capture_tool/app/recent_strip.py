"""The 'recent captures' strip at the bottom of the screen when a capture starts: the newest saved
captures as thumbnails - one click opens that picture with every capture button. Image files can
be dropped on it too. Thumbnails are read after the capture screen is up (it never waits)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

THUMB = QSize(132, 84)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")

STYLE = """
QWidget#recent { background: #1B1F2A; border: 1px solid #353C4E; border-radius: 14px; }
QLabel { color: #C9CFDB; font-size: 12px; }
QToolButton { border: 1px solid #353C4E; border-radius: 8px; background: #262C3A; color: #E9ECF2;
              font-size: 10px; padding: 3px; }
QToolButton:hover { border: 1.5px solid #5A92FA; background: #2D3446; }
QToolButton#close { border: none; background: transparent; font-size: 14px; color: #8A93A6; }
QToolButton#close:hover { color: #FFFFFF; }
"""


def image_paths(urls) -> list[str]:
    out = []
    for u in urls:
        p = u.toLocalFile() if hasattr(u, "toLocalFile") else str(u)
        if p and Path(p).suffix.lower() in IMAGE_SUFFIXES:
            out.append(p)
    return out


class RecentStrip(QWidget):
    open_path = Signal(str)

    def __init__(self, parent, sync: bool = False):
        super().__init__(parent)
        self.setObjectName("recent")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self._sync = sync
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel("최근 캡처 — 눌러서 다시 쓰기 · 그림 파일을 여기에 끌어다 놓아도 됩니다")
        top.addWidget(self.title, 1)
        close = QToolButton()
        close.setObjectName("close")
        close.setText("✕")
        close.setToolTip("이번에는 숨기기 (설정에서 끌 수 있습니다)")
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.hide)
        top.addWidget(close)
        v.addLayout(top)
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        v.addLayout(self.row)
        self.buttons: list[QToolButton] = []
        self.paths: list[Path] = []

    def set_paths(self, paths: list[Path]) -> None:
        for b in self.buttons:
            self.row.removeWidget(b)
            b.deleteLater()
        self.buttons, self.paths = [], list(paths)
        for p in self.paths:
            b = QToolButton()
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(THUMB)
            b.setFixedSize(THUMB.width() + 12, THUMB.height() + 28)
            try:
                when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%m/%d %H:%M")
            except OSError:
                when = p.stem[:14]
            b.setText(when)
            b.setToolTip(f"{p.name}\n눌러서 이 캡처를 다시 엽니다 (표·텍스트·PPT·메일… 모두 사용)")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, path=str(p): self.open_path.emit(path))
            self.row.addWidget(b)
            self.buttons.append(b)
        self.adjustSize()
        if self._sync:
            self._load_thumbs()
        else:
            QTimer.singleShot(0, self._load_thumbs)              # after the capture screen is up

    def _load_thumbs(self) -> None:
        for b, p in zip(list(self.buttons), self.paths):
            r = QImageReader(str(p))
            size = r.size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                r.setScaledSize(size.scaled(THUMB, Qt.KeepAspectRatio))
            img = r.read()
            if not img.isNull():
                try:
                    b.setIcon(QIcon(QPixmap.fromImage(img)))
                except RuntimeError:                          # the strip went away meanwhile
                    return

    def place(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        self.adjustSize()
        self.move(max(8, (p.width() - self.width()) // 2), max(8, p.height() - self.height() - 56))

    # dropping image files on it
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and image_paths(e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = image_paths(e.mimeData().urls())
        if paths:
            e.acceptProposedAction()
            self.open_path.emit(paths[0])
