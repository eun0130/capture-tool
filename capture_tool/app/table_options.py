"""표 options: where the table goes (Excel / PowerPoint) and how it looks (the capture's colours
or white background with black text). Asked the first time; "다음부터 바로" skips it later."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

TARGETS = [("excel", "엑셀에 넣기", "열린 엑셀의 선택한 칸에 (닫혀 있으면 Ctrl+V)"), ("ppt", "PPT에 넣기", "새 슬라이드에 고칠 수 있는 표로"),
           ("word", "워드에 넣기", "열린 문서의 커서 위치에 표로")]
STYLES = [("keep", "캡처 모양 그대로", "칸 색·글자색·굵게까지"), ("plain", "흰 바탕 · 검은 글씨", "선만 있는 깔끔한 표 (문서용)")]


class TableOptions(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("표 복사")
        v = QVBoxLayout(self)
        self.buttons: dict[str, QPushButton] = {}
        self._choice = {"target": settings.table_target, "style": settings.table_style}
        for title, key, options in (("어디에 붙일까요?", "target", TARGETS), ("모양", "style", STYLES)):
            v.addWidget(QLabel(title))
            grid = QGridLayout()
            group = QButtonGroup(self)
            for i, (val, label, sub) in enumerate(options):
                b = QPushButton(f"{label}\n{sub}")
                b.setCheckable(True)
                b.setMinimumHeight(54)
                b.setChecked(self._choice[key] == val)
                b.clicked.connect(lambda _=False, k=key, x=val: self._pick(k, x))
                group.addButton(b)
                grid.addWidget(b, 0, i)
                self.buttons[val] = b
            v.addLayout(grid)
        self.quick = QCheckBox("다음부터 이 설정으로 바로 (표 버튼 한 번에, ▾ 메뉴에서 언제든 변경)")
        self.quick.setChecked(True)
        v.addWidget(self.quick)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton()
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.go)
        v.addLayout(row)
        self._update()

    def _pick(self, key: str, val: str) -> None:
        self._choice[key] = val
        self._update()

    def _update(self) -> None:
        t = dict((k, l) for k, l, _ in TARGETS)[self._choice["target"]]
        s = dict((k, l) for k, l, _ in STYLES)[self._choice["style"]]
        self.go.setText(f"{t} — {s} (Enter)")

    def result(self) -> tuple[str, str, bool]:
        return self._choice["target"], self._choice["style"], self.quick.isChecked()


def ask_table_options(settings, parent=None):
    d = TableOptions(settings, parent)
    return d.result() if d.exec() == QDialog.Accepted else None
