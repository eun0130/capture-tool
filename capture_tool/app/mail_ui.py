"""메일: choose recipients (address book, groups, typed addresses), the mail service, and the
paste helper that stays next to the browser's compose page. Nothing is sent by the app."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.contacts import AddressBook, BookFull, InvalidEmail, export_csv, import_csv, normalize_email
from ..core.mailcompose import PROVIDERS, suggest

TABS = [("frequent", "자주"), ("recent", "최근"), ("groups", "그룹"), ("all", "전체 주소록")]
ORDER = ["naver", "gmail", "naverworks", "daum", "outlook", "mailto", "custom"]
MAIN_SERVICES = [("naver", "네이버 메일"), ("gmail", "Gmail")]
MANY = 50                        # more recipients than this: say so before opening
AVATAR_COLORS = ["#1F5FD1", "#0F766E", "#B54708", "#7A3EB1", "#C2185B", "#2E7D32", "#455A64"]

STYLE = """
QDialog, QWidget#mailhelper { background: #FFFFFF; }
QLabel { color: #1D2330; font-size: 13px; }
QLabel#title { font-size: 18px; font-weight: 700; }
QLabel#sub { color: #5B6472; font-size: 12px; }
QLabel#section { color: #5B6472; font-size: 12px; font-weight: 600; }
QLineEdit { border: 1px solid #D5D9E0; border-radius: 10px; padding: 8px 12px; font-size: 13px; background: #FFFFFF; }
QLineEdit:focus { border: 1.5px solid #1F5FD1; }
QPushButton { border: 1px solid #D5D9E0; border-radius: 10px; padding: 7px 14px; background: #FFFFFF;
              color: #1D2330; font-size: 13px; }
QPushButton:hover { background: #F4F7FD; }
QPushButton#primary { background: #1F5FD1; color: #FFFFFF; border: none; font-weight: 600; padding: 9px 18px; }
QPushButton#primary:hover { background: #174AA6; }
QPushButton#pill { border-radius: 16px; padding: 6px 16px; background: #F1F3F5; border: none; color: #3A4150; }
QPushButton#pill:checked { background: #1F5FD1; color: #FFFFFF; font-weight: 600; }
QPushButton#tab { border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 6px 10px;
                  color: #5B6472; background: transparent; }
QPushButton#tab:checked { color: #1F5FD1; border-bottom: 2px solid #1F5FD1; font-weight: 600; }
QPushButton#seg { border-radius: 8px; padding: 4px 10px; font-size: 12px; background: #F1F3F5; border: none;
                  color: #5B6472; }
QPushButton#seg:checked { background: #E6EEFB; color: #1F5FD1; font-weight: 600; }
QPushButton#chip { border-radius: 14px; padding: 4px 10px; font-size: 12px; background: #E6EEFB; color: #1F5FD1;
                   border: none; }
QPushButton#chipcc { border-radius: 14px; padding: 4px 10px; font-size: 12px; background: #F1F3F5; color: #3A4150;
                     border: none; }
QPushButton#link { border: none; color: #1F5FD1; background: transparent; padding: 4px; }
QPushButton#step { text-align: left; padding: 10px 14px; }
QPushButton#done { text-align: left; padding: 10px 14px; background: #EAF8F0; border: 1px solid #1E9E57; color: #1E6B3A; }
QComboBox { border: 1px solid #D5D9E0; border-radius: 10px; padding: 6px 10px; font-size: 13px; background: #FFFFFF; }
QListWidget { border: none; outline: 0; }
QListWidget::item { border-bottom: 1px solid #EEF0F3; }
QListWidget::item:hover { background: #F6F8FB; }
QTableWidget { border: 1px solid #E3E6EB; border-radius: 8px; gridline-color: #EEF0F3; }
"""


@dataclass
class MailChoice:
    to: list[str]
    cc: list[str]
    provider: str
    new: dict = field(default_factory=dict)       # typed address -> name, added to the book


class _Row(QWidget):
    """One person or group: avatar, name, address, and 받는 사람 / 참조 toggles."""

    def __init__(self, key: str, name: str, detail: str, state: str | None, on_pick):
        super().__init__()
        self.key = key
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)
        self.avatar = QLabel(name[:1] if name else "?")
        color = AVATAR_COLORS[sum(map(ord, key)) % len(AVATAR_COLORS)]
        self.avatar.setFixedSize(34, 34)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(f"background: {color}; color: #FFFFFF; border-radius: 17px; font-weight: 700;")
        h.addWidget(self.avatar)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.detail_label = QLabel(detail)
        self.detail_label.setStyleSheet("color: #5B6472; font-size: 12px;")
        texts.addWidget(self.name_label)
        texts.addWidget(self.detail_label)
        h.addLayout(texts, 1)
        self.to_button = QPushButton("받는 사람")
        self.cc_button = QPushButton("참조")
        for b, fld in ((self.to_button, "to"), (self.cc_button, "cc")):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(state == fld)
            b.clicked.connect(lambda on, f=fld: on_pick(key, f if on else None))
            h.addWidget(b)
        self.setStyleSheet("background: transparent;")


class MailPicker(QDialog):
    def __init__(self, book: AddressBook, settings, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("메일로 보내기")
        self.setStyleSheet(STYLE)
        self.resize(560, 640)
        self.book, self.settings = book, settings
        self._picked: dict[str, str] = {}          # key ("a@b" or "group:이름") -> "to" | "cc"
        self._new: dict[str, str] = {}
        self._tab = "frequent"
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        title = QLabel("메일로 보내기")
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel("받는 사람을 고르고 [메일 쓰기]를 누르세요. 보내기는 메일 화면에서 직접 누릅니다.")
        sub.setObjectName("sub")
        v.addWidget(sub)

        # where to send from: the two common services as big buttons, the rest in a list
        srow = QHBoxLayout()
        lab = QLabel("보낼 메일")
        lab.setObjectName("section")
        srow.addWidget(lab)
        self.service_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(False)
        for pid, label in MAIN_SERVICES:
            b = QPushButton(label)
            b.setObjectName("pill")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, p=pid: self._set_service(p))
            srow.addWidget(b)
            self.service_buttons[pid] = b
        self.provider = QComboBox()
        for pid in ORDER:
            self.provider.addItem(PROVIDERS[pid].label, pid)
        self.provider.currentIndexChanged.connect(lambda _: self._sync_service())
        srow.addWidget(self.provider)
        srow.addStretch(1)
        v.addLayout(srow)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  이름·주소 찾기 — 새 주소는 입력하고 Enter (예: 홍길동 <hong@회사.com>)")
        self.search.textChanged.connect(lambda _: self._fill())
        self.search.returnPressed.connect(self.add_typed)
        v.addWidget(self.search)

        trow = QHBoxLayout()
        trow.setSpacing(4)
        self.tab_buttons: dict[str, QPushButton] = {}
        tgroup = QButtonGroup(self)
        for key, label in TABS:
            b = QPushButton(label)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            tgroup.addButton(b)
            trow.addWidget(b)
            self.tab_buttons[key] = b
        trow.addStretch(1)
        edit = QPushButton("주소·그룹 편집")
        edit.setObjectName("link")
        edit.clicked.connect(self._edit_book)
        trow.addWidget(edit)
        v.addLayout(trow)

        self.list = QListWidget()
        v.addWidget(self.list, 1)

        self.chip_area = QScrollArea()
        self.chip_area.setWidgetResizable(True)
        self.chip_area.setFixedHeight(46)
        self.chip_area.setFrameShape(QFrame.NoFrame)
        self.chip_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chip_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chip_host = QWidget()
        self._chip_row = QHBoxLayout(self._chip_host)
        self._chip_row.setContentsMargins(0, 4, 0, 4)
        self._chip_row.setSpacing(6)
        self.chip_area.setWidget(self._chip_host)
        v.addWidget(self.chip_area)
        self.chips = QLabel()                          # plain summary (also for screen readers)
        self.chips.setObjectName("sub")
        self.chips.setWordWrap(True)
        v.addWidget(self.chips)
        self.status = QLabel()
        self.status.setStyleSheet("color: #B42318; font-size: 12px;")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        self.go = QPushButton()
        self.go.setObjectName("primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        bottom.addWidget(cancel)
        bottom.addWidget(self.go)
        v.addLayout(bottom)

        want = settings.mail_provider or suggest(settings.mail_account) or "naver"
        self.provider.setCurrentIndex(max(0, self.provider.findData(want)))
        self._sync_service()
        self.set_tab("frequent" if book.uses else "all")

    # --- service --------------------------------------------------------------------------------
    def _set_service(self, pid: str) -> None:
        self.provider.setCurrentIndex(max(0, self.provider.findData(pid)))
        self._sync_service()

    def _sync_service(self) -> None:
        cur = self.provider.currentData()
        for pid, b in self.service_buttons.items():
            b.setChecked(pid == cur)

    # --- list -----------------------------------------------------------------------------------------
    def set_tab(self, key: str) -> None:
        self._tab = key
        for k, b in self.tab_buttons.items():
            b.setChecked(k == key)
        self._fill()

    def _entries(self) -> list[tuple[str, str, str]]:
        """(key, name, detail) for the current tab and search."""
        q = self.search.text().strip().lower()
        if self._tab == "groups":
            return [(f"group:{g.name}", g.name, f"그룹 · {len(g.members)}명") for g in self.book.groups
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
        keys = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        return [k for k in keys if k]

    def row_widget(self, key: str) -> _Row | None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == key:
                return self.list.itemWidget(it)
        return None

    def _fill(self) -> None:
        self.list.clear()
        entries = self._entries()
        for key, name, detail in entries:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, key)
            row = _Row(key, name, detail, self._picked.get(key), self._pick)
            it.setSizeHint(QSize(0, 52))
            self.list.addItem(it)
            self.list.setItemWidget(it, row)
        if not entries:
            it = QListWidgetItem("  아직 없습니다. 위 칸에 주소를 입력하고 Enter, 또는 [주소·그룹 편집]에서 추가하세요."
                                 if not self.search.text().strip() else "  찾는 이름·주소가 없습니다. 주소를 다 쓰고 Enter 하면 추가됩니다.")
            it.setFlags(Qt.NoItemFlags)
            it.setData(Qt.UserRole, None)
            self.list.addItem(it)
        self._update()

    def _pick(self, key: str, fld: str | None) -> None:
        if fld is None:
            self._picked.pop(key, None)
        else:
            self._picked[key] = fld
        row = self.row_widget(key)
        if row is not None:
            row.to_button.setChecked(fld == "to")
            row.cc_button.setChecked(fld == "cc")
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

    def _label(self, key: str) -> str:
        if key.startswith("group:"):
            return key[6:] + " (그룹)"
        c = self.book.get(key)
        return c.name if c is not None else (self._new.get(key) or key)

    def _update(self) -> None:
        while self._chip_row.count():
            w = self._chip_row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for key, fld in self._picked.items():
            chip = QPushButton(f"{'받는' if fld == 'to' else '참조'} · {self._label(key)}  ✕")
            chip.setObjectName("chip" if fld == "to" else "chipcc")
            chip.setToolTip("누르면 뺍니다")
            chip.clicked.connect(lambda _=False, k=key: self._pick(k, None))
            self._chip_row.addWidget(chip)
        self._chip_row.addStretch(1)
        c = self.choice()
        to, cc = self.book.resolve(c.to, c.cc)
        n = len(to) + len(cc)
        names = [self._label(k) for k in self._picked]
        self.chips.setText(("선택: " + ", ".join(names)) if names else "아직 고르지 않았습니다.")
        self.chip_area.setVisible(bool(names))
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
        self.setWindowTitle("주소·그룹 편집")
        self.setStyleSheet(STYLE)
        self.resize(600, 620)
        self.book = book
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        title = QLabel("주소·그룹 편집")
        title.setObjectName("title")
        v.addWidget(title)
        sub = QLabel("이 PC의 이 Windows 사용자만 열 수 있게 암호화해서 저장합니다. 인터넷에 올리지 않습니다.")
        sub.setObjectName("sub")
        v.addWidget(sub)
        sec = QLabel("주소")
        sec.setObjectName("section")
        v.addWidget(sec)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["이름", "메일 주소"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 160)
        v.addWidget(self.table, 1)
        r = QHBoxLayout()
        for label, fn in [("+ 추가", self._add_row), ("선택 삭제", self._del_rows), ("CSV 가져오기", self._import),
                          ("CSV 내보내기", self._export)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            r.addWidget(b)
        v.addLayout(r)
        sec2 = QLabel("그룹 — 이름을 쓰고 아래에서 사람을 체크한 뒤 [그룹 저장]")
        sec2.setObjectName("section")
        v.addWidget(sec2)
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
        ok.setObjectName("primary")
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
    """Next to the browser's compose page. When the service already filled To / Cc / Subject
    only the capture step shows; the others wait under '다시 복사' for a field that came out empty."""

    IDLE_MS = 180_000

    def __init__(self, copy, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setObjectName("mailhelper")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.setWindowTitle("메일 붙여넣기 도우미")
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._copy = copy
        self._texts: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._capture = None
        self._save = None
        self._prefilled = False
        self._counts = {"to": 0, "cc": 0}
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(8)
        title = QLabel("메일 붙여넣기 도우미")
        title.setObjectName("title")
        v.addWidget(title)
        self.hint = QLabel()
        self.hint.setObjectName("sub")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.buttons: dict[str, QPushButton] = {}
        for key in ("capture", "to", "cc", "subject", "file"):
            b = QPushButton()
            b.setObjectName("primary" if key == "capture" else ("link" if key == "file" else "step"))
            b.setMinimumHeight(40 if key != "file" else 28)
            b.clicked.connect(lambda _=False, k=key: self._press(k))
            v.addWidget(b)
            self.buttons[key] = b
        self.again = QPushButton("받는 사람·참조·제목 다시 복사 ▾")
        self.again.setObjectName("link")
        self.again.clicked.connect(self._show_steps)
        v.addWidget(self.again)
        close = QPushButton("닫기")
        close.clicked.connect(self.close)
        v.addWidget(close)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self.close)
        self.setMinimumWidth(340)

    def set_data(self, to: list[str], cc: list[str], subject: str, prefilled: bool, capture_payload, save,
                 what: str = "캡처") -> None:
        """what: "캡처" (the picture) or "글자" (text mode: the text that was copied)."""
        from ..core.mailcompose import recipients_text
        self._texts = {"to": recipients_text(to), "cc": recipients_text(cc), "subject": subject}
        self._counts = {"to": len(to), "cc": len(cc)}
        self._labels = {"to": f"① 받는 사람 칸에 붙일 주소 복사 ({len(to)}명)",
                        "cc": f"② 참조 칸에 붙일 주소 복사 ({len(cc)}명)",
                        "subject": "③ 제목 칸에 붙일 제목 복사",
                        "capture": f"{what} 복사 → 본문에 Ctrl+V",
                        "file": "붙여넣기가 막히면: 캡처를 파일로 저장(첨부용)"}
        self._capture, self._save, self._prefilled = capture_payload, save, prefilled
        for k, b in self.buttons.items():
            b.setText(self._labels[k])
        self.buttons["capture"].setVisible(capture_payload is not None)
        if prefilled:
            self.hint.setText("받는 사람·참조·제목은 메일 화면에 이미 채워져 있습니다. 본문을 누르고 Ctrl+V 하면 " + what + "가 붙습니다. "
                              "[보내기]는 직접 누르세요.")
            self._set_steps_visible(False)
            self.again.setVisible(bool(to or cc))
        else:
            self.hint.setText("메일 화면의 각 칸을 누르고, 아래 버튼을 누른 뒤 Ctrl+V. 받는 사람은 이미 복사되어 있습니다. "
                              "[보내기]는 직접 누르세요. 로그인 화면이 나오면 로그인 후 계속하세요.")
            self._set_steps_visible(True)
            self.again.setVisible(False)
        self._idle.start(self.IDLE_MS)

    def _set_steps_visible(self, on: bool) -> None:
        self.buttons["to"].setVisible(on and self._counts["to"] > 0)
        self.buttons["cc"].setVisible(on and self._counts["cc"] > 0)
        self.buttons["subject"].setVisible(on)
        self.adjustSize()

    def _show_steps(self) -> None:
        self._set_steps_visible(True)
        self.again.setVisible(False)

    def press(self, key: str) -> None:
        self._press(key)

    def _press(self, key: str) -> None:
        self._idle.start(self.IDLE_MS)
        if key == "file":
            if self._save:
                self._save()
            return
        payload = self._capture if key == "capture" else {"CF_UNICODETEXT": self._texts[key]}
        if payload and self._copy(payload):
            for k, b in self.buttons.items():
                done = k == key
                b.setText(self._labels[k] + ("   ✓ 복사됨" if done else ""))
                if k not in ("capture", "file"):
                    b.setObjectName("done" if done else "step")
                    b.style().unpolish(b)
                    b.style().polish(b)

    def place(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.adjustSize()
            self.move(g.right() - self.width() - 24, g.top() + 120)
