"""Recognized-text panel: copy all / selected / as table, toggle PII masking, QR result."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ..core.clipboard_payload import text_payload
from ..core.ocr import OcrLine, full_text
from ..core.redact import find_pii
from ..core.table import to_grid


def mask(text: str) -> str:
    out = list(text)
    for m in find_pii(text):
        for i in range(m.start, m.end):
            if not out[i].isspace():
                out[i] = "*"
    return "".join(out)


class TextPanel(QWidget):
    def __init__(self, lines: list[OcrLine], clipboard_set, redact: bool = True, qr: str | None = None, notify=None,
                 grid: list[list[str]] | None = None):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("인식된 텍스트 — Esc로 닫기")
        self.lines = lines
        self.grid = grid
        self._set = clipboard_set
        self._notify = notify or (lambda m: None)
        self.resize(420, 360)
        v = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>인식된 텍스트</b>"))
        head.addStretch(1)
        head.addWidget(QLabel("한/영 · 오프라인"))
        v.addLayout(head)
        self.edit = QPlainTextEdit()
        v.addWidget(self.edit)
        if qr:
            v.addWidget(QLabel(f"QR 인식: {qr}"))
        self.redact = QCheckBox("개인정보 자동 가림 (이메일·전화·주민번호·카드번호)")
        self.redact.setChecked(redact)
        self.redact.toggled.connect(self._refresh)
        v.addWidget(self.redact)
        row = QHBoxLayout()
        for label, fn in [("전체 복사", self.copy_all), ("선택 부분 복사", self.copy_selected),
                          ("표로 복사 (Excel)", self.copy_table), ("닫기 (Esc)", self.close)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.close_button = b
        v.addLayout(row)
        self._refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def _clean(self, t: str) -> str:
        return mask(t) if self.redact.isChecked() else t

    def _refresh(self) -> None:
        self.edit.setPlainText(self._clean(full_text(self.lines)))

    def copy_all(self) -> None:
        self._set(text_payload(self.edit.toPlainText()))
        self._notify("전체 텍스트를 복사했습니다.")

    def copy_selected(self) -> None:
        t = self.edit.textCursor().selectedText().replace(" ", "\n")
        if t.strip():
            self._set(text_payload(t))
            self._notify("선택한 텍스트를 복사했습니다.")

    def copy_table(self) -> None:
        grid = self.grid or to_grid([(l.text, *l.box) for l in self.lines])
        grid = [[self._clean(c) for c in row] for row in grid]
        if grid:
            self._set(text_payload("", table=grid))
            self._notify("표로 복사했습니다. Excel에 붙여넣으면 칸이 나뉩니다.")
