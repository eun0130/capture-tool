"""Every pinned capture in one place: bring one forward, line them up on the right, hide or
half-fade them all, close them all."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget


class PinManager(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.c = controller
        self.setWindowTitle("고정한 캡처")
        self.resize(420, 300)
        v = QVBoxLayout(self)
        self.title = QLabel()
        v.addWidget(self.title)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(96, 64))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.itemClicked.connect(lambda it: self.select(self.list.row(it)))
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for key, label, fn in [("arrange", "오른쪽에 나란히", controller.arrange_pins),
                               ("hide", "모두 숨기기/보이기", controller.toggle_pins_hidden),
                               ("fade", "모두 반투명/또렷", controller.toggle_pins_faded),
                               ("close", "모두 닫기", controller.close_all_pins)]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=fn: (f(), self.refresh()))
            row.addWidget(b)
            self.buttons[key] = b
        v.addLayout(row)

    def count(self) -> int:
        return self.list.count()

    def refresh(self) -> None:
        self.list.clear()
        for i, p in enumerate(self.c.pins):
            it = QListWidgetItem(QIcon(p.pixmap), f"{i + 1}")
            it.setToolTip("누르면 앞으로 가져옵니다")
            self.list.addItem(it)
        self.title.setText(f"<b>고정한 캡처 {len(self.c.pins)}개</b> — 누르면 그 캡처를 앞으로")

    def select(self, i: int) -> None:
        if 0 <= i < len(self.c.pins):
            p = self.c.pins[i]
            p.show()
            p.raise_()
            p.activateWindow()
