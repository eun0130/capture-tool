"""메일: choose recipients (address book, groups, typed addresses), the mail service, and the
paste helper that stays next to the browser's compose page. Nothing is sent by the app."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QTabBar, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.contacts import AddressBook, BookFull, InvalidEmail, export_csv, import_csv, normalize_email
from ..core.mailcompose import PROVIDERS, suggest

TABS = [("frequent", "자주"), ("recent", "최근"), ("groups", "그룹"), ("all", "전체 주소록")]
ORDER = ["naver", "gmail", "naverworks", "daum", "outlook", "mailto", "custom"]
MANY = 50                        # more recipients than this: say so before opening


@dataclass
class MailChoice:
    to: list[str]
    cc: list[str]
    provider: str
    new: dict = field(default_factory=dict)       # typed address -> name, added to the book


class MailPicker(QDialog):
    def __init__(self, book: AddressBook, settings, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("메일로 보내기 — 받는 사람 고르기")
        self.resize(520, 560)
        self.book, self.settings = book, settings
        self._picked: dict[str, str] = {}          # key ("a@b" or "group:이름") -> "to" | "cc"
        self._new: dict[str, str] = {}
        self._tab = "frequent"
        v = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름·주소 찾기 — 새 주소는 입력하고 Enter (예: 홍길동 <hong@회사.com>)")
        self.search.textChanged.connect(lambda _: self._fill())
        self.search.returnPressed.connect(self.add_typed)
        v.addWidget(self.search)
        self.tabs = QTabBar()
        for _, label in TABS:
            self.tabs.addTab(label)
        self.tabs.currentChanged.connect(lambda i: self.set_tab(TABS[i][0]))
        v.addWidget(self.tabs)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["이름", "주소", "넣을 곳"])
        self.list.setColumnWidth(0, 150)
        self.list.setColumnWidth(1, 220)
        self.list.itemChanged.connect(self._item_changed)
        v.addWidget(self.list, 1)
        self.chips = QLabel()
        self.chips.setWordWrap(True)
        v.addWidget(self.chips)
        self.status = QLabel()
        self.status.setStyleSheet("color: #B42318;")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(QLabel("보낼 메일"))
        self.provider = QComboBox()
        for pid in ORDER:
            self.provider.addItem(PROVIDERS[pid].label, pid)
        want = settings.mail_provider or suggest(settings.mail_account) or "naver"
        self.provider.setCurrentIndex(max(0, self.provider.findData(want)))
        row.addWidget(self.provider, 1)
        edit = QPushButton("주소·그룹 편집")
        edit.clicked.connect(self._edit_book)
        row.addWidget(edit)
        v.addLayout(row)
        bottom = QHBoxLayout()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton()
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        bottom.addStretch(1)
        bottom.addWidget(cancel)
        bottom.addWidget(self.go)
        v.addLayout(bottom)
        self.set_tab("frequent" if book.uses else "all")

    # --- list ----------------------------------------------------------------------------------
    def set_tab(self, key: str) -> None:
        self._tab = key
        idx = [k for k, _ in TABS].index(key)
        if self.tabs.currentIndex() != idx:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(idx)
            self.tabs.blockSignals(False)
        self._fill()

    def _entries(self) -> list[tuple[str, str, str]]:
        """(key, name, detail) for the current tab and search."""
        q = self.search.text().strip().lower()
        if self._tab == "groups":
            return [(f"group:{g.name}", g.name, f"{len(g.members)}명") for g in self.book.groups
                    if not q or q in g.name.lower()]
        if self._tab == "recent":
            people = [self.book.get(e) for e in self.book.recent]
            people = [p for p in people if p is not None]
        elif self._tab == "frequent":
            people = self.book.frequent(12)
        else:
            people = list(self.book.contacts)
        return [(p.email, p.name, p.email) for p in people
                if not q or q in p.name.lower() or q in p.email.lower()]

    def rows(self) -> list[str]:
        return [self.list.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.list.topLevelItemCount())]

    def _fill(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for key, name, detail in self._entries():
            it = QTreeWidgetItem([name, detail, ""])
            it.setData(0, Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if key in self._picked else Qt.Unchecked)
            self.list.addTopLevelItem(it)
            box = QComboBox()
            box.addItem("받는 사람", "to")
            box.addItem("참조", "cc")
            box.setCurrentIndex(1 if self._picked.get(key) == "cc" else 0)
            box.currentIndexChanged.connect(lambda _i, k=key, b=box: self._field_changed(k, b.currentData()))
            self.list.setItemWidget(it, 2, box)
        self.list.blockSignals(False)
        self._update()

    def _item_changed(self, it, col) -> None:
        if col != 0:
            return
        key = it.data(0, Qt.UserRole)
        box = self.list.itemWidget(it, 2)
        if it.checkState(0) == Qt.Checked:
            self._picked[key] = box.currentData() if box else "to"
        else:
            self._picked.pop(key, None)
        self._update()

    def _field_changed(self, key: str, fld: str) -> None:
        if key in self._picked:
            self._picked[key] = fld
            self._update()

    def check(self, key: str, field: str = "to") -> None:
        self._picked[key] = field
        self._fill()

    def add_typed(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        try:
            email = normalize_email(text)
        except InvalidEmail:
            self.status.setText("올바른 메일 주소가 아닙니다. 예: hong@회사.com")
            return
        name = text.split("<", 1)[0].strip() if "<" in text else ""
        if self.book.get(email) is None:
            self._new[email] = name
        self._picked[email] = "to"
        self.search.clear()
        self.status.clear()
        self._update()

    def _update(self) -> None:
        c = self.choice()
        to, cc = self.book.resolve(c.to, c.cc)
        n = len(to) + len(cc)
        names = [k[6:] + "(그룹)" if k.startswith("group:") else k for k in self._picked]
        self.chips.setText(("선택: " + ", ".join(names)) if names else "아직 고르지 않았습니다.")
        self.go.setText(f"선택한 {n}명에게 메일 쓰기" if n else "받는 사람 없이 새 메일 쓰기")
        if n > MANY:
            self.status.setText(f"받는 사람이 {n}명입니다. 메일 서비스의 한도에 걸릴 수 있습니다.")
        elif self.status.text().startswith("받는 사람이"):
            self.status.clear()

    def choice(self) -> MailChoice:
        to = [k for k, f in self._picked.items() if f == "to"]
        cc = [k for k, f in self._picked.items() if f == "cc"]
        return MailChoice(to, cc, self.provider.currentData(), dict(self._new))

    def _edit_book(self) -> None:
        ContactsDialog(self.book, self).exec()
        self._fill()


def ask_mail(book: AddressBook, settings, parent=None) -> MailChoice | None:
    d = MailPicker(book, settings, parent)
    return d.choice() if d.exec() == QDialog.Accepted else None


class ContactsDialog(QDialog):
    """Edit addresses and groups; CSV import (Gmail / Naver / Excel) and export."""

    def __init__(self, book: AddressBook, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("주소·그룹 편집 (이 PC의 이 Windows 사용자만, 암호화해서 저장)")
        self.resize(560, 560)
        self.book = book
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>주소</b>"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["이름", "메일 주소"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        r = QHBoxLayout()
        for label, fn in [("+ 추가", self._add_row), ("선택 삭제", self._del_rows), ("CSV 가져오기", self._import),
                          ("CSV 내보내기", self._export)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            r.addWidget(b)
        v.addLayout(r)
        v.addWidget(QLabel("<b>그룹</b> — 이름을 쓰고 아래 주소를 체크한 뒤 [그룹 저장]"))
        g = QHBoxLayout()
        self.group_name = QComboBox()
        self.group_name.setEditable(True)
        self.group_name.addItems([x.name for x in book.groups])
        self.group_name.currentTextChanged.connect(self._load_group)
        g.addWidget(self.group_name, 1)
        save_g = QPushButton("그룹 저장")
        save_g.clicked.connect(self._save_group)
        del_g = QPushButton("그룹 삭제")
        del_g.clicked.connect(self._del_group)
        g.addWidget(save_g)
        g.addWidget(del_g)
        v.addLayout(g)
        self.members = QListWidget()
        v.addWidget(self.members, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        ok = QPushButton("저장하고 닫기")
        ok.clicked.connect(self._apply)
        v.addWidget(ok)
        self._load()

    def _load(self) -> None:
        self.table.setRowCount(0)
        for c in self.book.contacts:
            self._add_row(c.name, c.email)
        self._load_group(self.group_name.currentText())

    def _add_row(self, name: str = "", email: str = "") -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name if isinstance(name, str) else ""))
        self.table.setItem(r, 1, QTableWidgetItem(email if isinstance(email, str) else ""))

    def _del_rows(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _load_group(self, name: str) -> None:
        g = self.book.group(name)
        chosen = {m.lower() for m in (g.members if g else [])}
        self.members.clear()
        for c in self.book.contacts:
            it = QListWidgetItem(f"{c.name} <{c.email}>")
            it.setData(Qt.UserRole, c.email)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c.email.lower() in chosen else Qt.Unchecked)
            self.members.addItem(it)

    def _save_group(self) -> None:
        members = [self.members.item(i).data(Qt.UserRole) for i in range(self.members.count())
                   if self.members.item(i).checkState() == Qt.Checked]
        try:
            self.book.add_group(self.group_name.currentText(), members)
        except (ValueError, BookFull) as e:
            self.status.setText(str(e))
            return
        if self.group_name.findText(self.group_name.currentText()) < 0:
            self.group_name.addItem(self.group_name.currentText())
        self.status.setText(f"그룹 '{self.group_name.currentText()}' {len(members)}명 저장")

    def _del_group(self) -> None:
        self.book.remove_group(self.group_name.currentText())
        i = self.group_name.findText(self.group_name.currentText())
        if i >= 0:
            self.group_name.removeItem(i)

    def apply_rows(self) -> list[str]:
        """Table -> book. Returns problems (bad rows are kept out, everything else saved)."""
        problems: list[str] = []
        wanted: dict[str, str] = {}
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            raw = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            if not raw and not name:
                continue
            try:
                wanted[normalize_email(raw).lower()] = name
                wanted.setdefault("__order__", "")
            except InvalidEmail:
                problems.append(f"{r + 1}번째 줄 주소가 올바르지 않습니다: {raw}")
        wanted.pop("__order__", None)
        for c in list(self.book.contacts):
            if c.email.lower() not in wanted:
                self.book.remove(c.email)
        for r in range(self.table.rowCount()):
            raw = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            try:
                e = normalize_email(raw)
            except InvalidEmail:
                continue
            try:
                self.book.add(wanted.get(e.lower(), ""), e)
            except BookFull as ex:
                problems.append(str(ex))
                break
        return problems

    def _apply(self) -> None:
        problems = self.apply_rows()
        if problems:
            self.status.setText("\n".join(problems[:5]))
            return
        self.accept()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "주소 CSV 가져오기", "", "CSV (*.csv);;모든 파일 (*.*)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read(20 * 1024 * 1024)
        except OSError as e:
            self.status.setText(f"파일을 열지 못했습니다: {e}")
            return
        found, skipped = import_csv(data)
        for c in found:
            self._add_row(c.name, c.email)
        self.status.setText(f"{len(found)}개를 가져왔습니다" + (f", {len(skipped)}줄은 주소가 잘못되어 건너뜀" if skipped else "")
                            + ". [저장하고 닫기]를 눌러야 저장됩니다.")

    def _export(self) -> None:
        self.apply_rows()
        path, _ = QFileDialog.getSaveFileName(self, "주소 CSV 내보내기", "주소록.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(export_csv(self.book))
            self.status.setText("내보냈습니다. 메일 주소가 들어 있는 파일이니 보관에 주의하세요.")
        except OSError as e:
            QMessageBox.warning(self, "내보내기", f"저장하지 못했습니다: {e}")


class MailHelper(QWidget):
    """Next to the browser's compose page: copy To / Cc / Subject / the capture one by one."""

    IDLE_MS = 180_000

    def __init__(self, copy, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("메일 붙여넣기 도우미")
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._copy = copy
        self._texts: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._capture = None
        self._save = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>메일 붙여넣기 도우미</b>"))
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.buttons: dict[str, QPushButton] = {}
        for key in ("to", "cc", "subject", "capture", "file"):
            b = QPushButton()
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, k=key: self._press(k))
            v.addWidget(b)
            self.buttons[key] = b
        close = QPushButton("닫기")
        close.clicked.connect(self.close)
        v.addWidget(close)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self.close)

    def set_data(self, to: list[str], cc: list[str], subject: str, prefilled: bool, capture_payload, save) -> None:
        from ..core.mailcompose import recipients_text
        self._texts = {"to": recipients_text(to), "cc": recipients_text(cc), "subject": subject}
        self._labels = {"to": f"① 받는 사람 복사 ({len(to)}명)", "cc": f"② 참조 복사 ({len(cc)}명)",
                        "subject": "③ 제목 복사", "capture": "④ 캡처 복사 → 본문에 Ctrl+V",
                        "file": "붙여넣기가 막히면: 캡처를 파일로 저장(첨부용)"}
        self._capture, self._save = capture_payload, save
        for k, b in self.buttons.items():
            b.setText(self._labels[k])
        self.buttons["to"].setVisible(bool(to))
        self.buttons["cc"].setVisible(bool(cc))
        self.buttons["capture"].setVisible(capture_payload is not None)
        self.hint.setText("받는 사람·제목이 이미 채워져 있습니다. ④ 캡처만 본문에 붙이면 됩니다. [보내기]는 직접 누르세요."
                          if prefilled else
                          "메일 쓰기 화면에서 칸을 누르고, 아래 버튼을 누른 뒤 Ctrl+V. 위에서부터 차례로. "
                          "[보내기]는 직접 누르세요. 로그인 화면이 나오면 로그인 후 계속하세요.")
        self._idle.start(self.IDLE_MS)

    def _press(self, key: str) -> None:
        self._idle.start(self.IDLE_MS)
        if key == "file":
            if self._save:
                self._save()
            return
        payload = self._capture if key == "capture" else {"CF_UNICODETEXT": self._texts[key]}
        if payload and self._copy(payload):
            for k, b in self.buttons.items():
                b.setText(self._labels[k] + ("   ✓ 복사됨" if k == key else ""))

    def place(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.adjustSize()
            self.move(g.right() - self.width() - 24, g.top() + 120)
