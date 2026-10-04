"""표로 붙여넣기 미리보기: text that isn't laid out as a table, split by a rule the person picks,
editable cell by cell, then copied as a table or sent to PowerPoint."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.table_split import split_table

RULE_LABELS = [("auto", "자동"), ("pair", "\"항목: 값\" 두 칸"), ("spaces", "띄어쓰기 2칸 이상·탭"), ("comma", "쉼표 ,"),
               ("line", "한 줄 = 한 칸"), ("custom", "직접 입력")]


class TablePreview(QDialog):
    def __init__(self, lines: list[str], parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("표로 붙여넣기 — 이렇게 붙습니다")
        self.resize(720, 560)
        self.lines = list(lines)
        self.rule = "auto"
        self.action = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel("칸 나누는 기준"))
        rules = QHBoxLayout()
        self.rule_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, label in RULE_LABELS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_rule(k))
            group.addButton(b)
            rules.addWidget(b)
            self.rule_buttons[key] = b
        self.custom = QLineEdit("|")
        self.custom.setMaximumWidth(60)
        self.custom.setToolTip("직접 입력할 구분 글자")
        self.custom.textChanged.connect(lambda _: self.rule == "custom" and self._refresh())
        rules.addWidget(self.custom)
        v.addLayout(rules)
        opts = QHBoxLayout()
        self.title_first = QCheckBox("첫 줄은 제목(표 위 글상자로)")
        self.title_first.setChecked(True)
        self.bullets = QCheckBox("글머리표(•) 빼기")
        self.bullets.setChecked(True)
        self.header = QCheckBox("머리글 행 추가")
        for w in (self.title_first, self.bullets, self.header):
            w.toggled.connect(lambda _: self._refresh())
            opts.addWidget(w)
        opts.addStretch(1)
        v.addLayout(opts)
        self.title_label = QLabel()
        v.addWidget(self.title_label)
        self.table = QTableWidget()
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        edit = QHBoxLayout()
        for label, fn in [("+ 줄", self.add_row), ("− 줄", self.del_row), ("+ 칸", self.add_col), ("− 칸", self.del_col)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            edit.addWidget(b)
        self.size_label = QLabel()
        edit.addStretch(1)
        edit.addWidget(self.size_label)
        v.addLayout(edit)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        for label, act in [("취소", None), ("워드에 넣기", "word"), ("PPT 표로 넣기", "ppt"), ("표로 복사 (Enter)", "copy")]:
            b = QPushButton(label)
            if act == "copy":
                b.setDefault(True)
            b.clicked.connect(lambda _=False, a=act: self._finish(a))
            bottom.addWidget(b)
        v.addLayout(bottom)
        self._title = None
        self.set_rule("auto")

    def set_rule(self, key: str) -> None:
        self.rule = key
        self.rule_buttons[key].setChecked(True)
        self._refresh()

    def _rule_value(self) -> str:
        return f"custom:{self.custom.text()}" if self.rule == "custom" else self.rule

    def _refresh(self) -> None:
        title, rows = split_table(self.lines, self._rule_value(), title_first=self.title_first.isChecked(),
                                  strip_bullets=self.bullets.isChecked(), header=self.header.isChecked())
        self._title = title
        self.title_label.setText(f"제목: {title}" if title else "제목 없음")
        cols = len(rows[0]) if rows else 0
        self.table.clear()
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(cols)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()
        self._size()

    def _size(self) -> None:
        self.size_label.setText(f"{self.table.rowCount()}행 × {self.table.columnCount()}열 · 칸을 눌러 고칠 수 있음")

    def add_row(self) -> None:
        self.table.insertRow(self.table.rowCount())
        self._size()

    def del_row(self) -> None:
        r = self.table.currentRow()
        self.table.removeRow(r if r >= 0 else self.table.rowCount() - 1)
        self._size()

    def add_col(self) -> None:
        self.table.insertColumn(self.table.columnCount())
        self._size()

    def del_col(self) -> None:
        c = self.table.currentColumn()
        if self.table.columnCount() > 1:
            self.table.removeColumn(c if c >= 0 else self.table.columnCount() - 1)
        self._size()

    def result_rows(self) -> tuple[str | None, list[list[str]]]:
        rows = []
        for r in range(self.table.rowCount()):
            row = [(self.table.item(r, c).text() if self.table.item(r, c) else "").strip()
                   for c in range(self.table.columnCount())]
            if any(row):
                rows.append(row)
        return self._title, rows

    def _finish(self, action) -> None:
        self.action = action
        self.accept() if action else self.reject()


def ask_table_preview(lines: list[str], parent=None):
    """-> (action "copy" | "ppt" | "word", title, rows) or None when cancelled."""
    d = TablePreview(lines, parent)
    if d.exec() != QDialog.Accepted or d.action is None:
        return None
    title, rows = d.result_rows()
    return d.action, title, rows
