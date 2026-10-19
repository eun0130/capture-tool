"""Settings: record hotkeys by pressing them, save folder, file naming, format, startup."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..core.hotkey import HotkeyError, find_duplicates, is_reserved, known_conflicts, parse
from ..core.settings import Settings

ACTIONS = [("capture", "캡처 + 그리기"), ("ocr", "텍스트 바로 복사"), ("shapes", "도형 바로 복사 (PPT)"),
           ("fullscreen", "전체 화면 캡처"), ("scroll", "스크롤 캡처")]
_KEYNAMES = {Qt.Key_QuoteLeft: "`", Qt.Key_AsciiTilde: "`", Qt.Key_Print: "PrintScreen", Qt.Key_Space: "Space",
             Qt.Key_Tab: "Tab", Qt.Key_Insert: "Insert", Qt.Key_Delete: "Delete", Qt.Key_Home: "Home",
             Qt.Key_End: "End", Qt.Key_PageUp: "PageUp", Qt.Key_PageDown: "PageDown", Qt.Key_Left: "Left",
             Qt.Key_Right: "Right", Qt.Key_Up: "Up", Qt.Key_Down: "Down", Qt.Key_Pause: "Pause",
             Qt.Key_Minus: "-", Qt.Key_Equal: "=", Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]",
             Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'", Qt.Key_Comma: ",", Qt.Key_Period: ".",
             Qt.Key_Slash: "/", Qt.Key_Backslash: "\\"}
_SHIFTED_DIGITS = {Qt.Key_Exclam: "1", Qt.Key_At: "2", Qt.Key_NumberSign: "3", Qt.Key_Dollar: "4",
                   Qt.Key_Percent: "5", Qt.Key_AsciiCircum: "6", Qt.Key_Ampersand: "7", Qt.Key_Asterisk: "8",
                   Qt.Key_ParenLeft: "9", Qt.Key_ParenRight: "0"}


def key_name(key: int) -> str | None:
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"F{key - Qt.Key_F1 + 1}"
    return _KEYNAMES.get(key) or _SHIFTED_DIGITS.get(key)


class HotkeyEdit(QLineEdit):
    """Click, then press the combination. Backspace/Delete alone clears it."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setReadOnly(True)
        self.setPlaceholderText("클릭 후 키 조합을 누르세요 (비우면 사용 안 함)")

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R):
            return
        if k in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Escape) and not mods:
            self.setText("")
            return
        name = key_name(k)
        if name is None:
            return
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.AltModifier:
            parts.append("Alt")
        if mods & Qt.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.MetaModifier:
            parts.append("Win")
        parts.append(name)
        try:
            self.setText(str(parse("+".join(parts))))
        except HotkeyError:
            self.setText("+".join(parts))


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("캡처 도구 설정")
        self.setMinimumWidth(560)
        self._base = settings
        body = QWidget()                               # scrolls: the page is taller than a small screen
        v = QVBoxLayout(body)
        v.addWidget(QLabel("<b>단축키</b> — 입력칸을 클릭하고 원하는 키 조합을 누르면 됩니다."))
        form = QFormLayout()
        self.edits: dict[str, HotkeyEdit] = {}
        for action, label in ACTIONS:
            ed = HotkeyEdit(settings.hotkeys.get(action, ""))
            ed.textChanged.connect(self._show_problems)
            self.edits[action] = ed
            form.addRow(label, ed)
        v.addLayout(form)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #7A3E00;")
        v.addWidget(self.problems)

        v.addWidget(QLabel("<b>저장</b>"))
        sform = QFormLayout()
        row = QHBoxLayout()
        self.save_dir = QLineEdit(settings.save_dir)
        self.save_dir.setPlaceholderText("비우면 사진\\Captures")
        browse = QPushButton("찾아보기")
        browse.clicked.connect(self._browse)
        row.addWidget(self.save_dir)
        row.addWidget(browse)
        sform.addRow("저장 폴더", row)
        self.pattern = QLineEdit(settings.filename_pattern)
        self.pattern.setToolTip("{yymmdd} 날짜(261004), {date} 날짜(20261004), {time} 시간, {datetime} 날짜_시간")
        sform.addRow("파일 이름 규칙", self.pattern)
        self.fmt = QComboBox()
        self.fmt.addItems(["png", "jpg"])
        self.fmt.setCurrentText(settings.image_format)
        sform.addRow("파일 형식", self.fmt)
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(settings.jpg_quality)
        sform.addRow("JPG 품질", self.quality)
        v.addLayout(sform)
        self.auto_save = QCheckBox("캡처하면 자동으로 저장 폴더에 저장 (복사·PPT·고정·텍스트 등 무엇을 하든, Esc로 그냥 닫으면 저장 안 함)")
        self.auto_save.setChecked(settings.auto_save)
        self.redact = QCheckBox("텍스트 복사 시 개인정보 자동 가림")
        self.redact.setChecked(settings.redact_pii)
        self.startup = QCheckBox("Windows 시작 시 자동 실행")
        self.startup.setChecked(settings.launch_at_startup)
        self.ppt_new_slide = QCheckBox("PPT로 보낼 때 새 슬라이드에 넣기 (끄면 보고 있는 슬라이드에)")
        self.ppt_new_slide.setChecked(settings.ppt_new_slide)
        self.auto_copy = QCheckBox("영역을 고르면 바로 클립보드에 복사 (Ctrl+C 없이 Ctrl+V 가능, 그리면 복사본도 바뀜)")
        self.auto_copy.setChecked(settings.auto_copy)
        self.show_recent = QCheckBox("캡처를 시작하면 최근 캡처(저장한 것)를 아래에 보여 주기 — 눌러서 다시 쓰기")
        self.show_recent.setChecked(getattr(settings, "show_recent", True))
        self.pdf_one_page = QCheckBox("PDF로 저장할 때 긴 캡처도 한 쪽에 맞추기 (끄면 여러 쪽으로 나눔)")
        self.pdf_one_page.setChecked(getattr(settings, "pdf_one_page", False))
        self.keep_style = QCheckBox("PPT·도형·표로 보낼 때 색·글꼴 모양 그대로 (끄면 기본 모양: 흰 바탕·검은 글자)")
        self.keep_style.setChecked(settings.keep_style)
        self.update_check = QCheckBox("새 버전을 하루 한 번 확인해 알려 주기 (트레이 메뉴 '업데이트 확인…'으로 직접 확인도 가능)")
        self.update_check.setChecked(getattr(settings, "update_check", True))
        for w in (self.auto_save, self.auto_copy, self.show_recent, self.redact, self.startup, self.ppt_new_slide, self.pdf_one_page, self.keep_style,
                  self.update_check):
            v.addWidget(w)
        self.update_source = QLineEdit(getattr(settings, "update_source", ""))
        self.update_source.setPlaceholderText("업데이트 받을 곳 — 비우면 GitHub. 회사라면 설치 파일을 둔 공유 폴더 경로(\\\\서버\\폴더)도 됩니다")
        v.addWidget(self.update_source)
        # --- action bar: a favourites row, the rest in groups, one arrangement per place ---------
        from .. import edition
        from ..core import bar_layout as bl
        self._profiles = {p: bl.profile_of(settings, p) for p in bl.WORKPLACES}
        self._place = "work" if edition.is_work() else (settings.workplace if settings.workplace in bl.WORKPLACES else "home")
        v.addWidget(QLabel("<b>버튼 막대</b> — 첫 줄은 즐겨찾기, 나머지는 전체 줄에 비슷한 것끼리. "
                           "캡처 중 버튼을 오른쪽 클릭해도 바꿀 수 있습니다."))
        prow = QHBoxLayout()
        prow.addWidget(QLabel("지금 장소"))
        self.place_home = QRadioButton("집")
        self.place_work = QRadioButton("회사")
        pg = QButtonGroup(self)
        pg.addButton(self.place_home)
        pg.addButton(self.place_work)
        (self.place_work if self._place == "work" else self.place_home).setChecked(True)
        self.place_home.toggled.connect(self._switch_place)
        prow.addWidget(self.place_home)
        prow.addWidget(self.place_work)
        prow.addWidget(QLabel("— 장소마다 다른 배치를 씁니다 (트레이 메뉴에서도 바꿈)"))
        prow.addStretch(1)
        if edition.is_work():
            for w in (self.place_home, self.place_work):
                w.setEnabled(False)
        v.addLayout(prow)
        brow = QHBoxLayout()
        self.fav_list = QListWidget()
        self.fav_list.setFixedHeight(150)
        self.fav_list.setDragDropMode(QAbstractItemView.InternalMove)     # drag to reorder, like the bar
        self.fav_list.setDefaultDropAction(Qt.MoveAction)
        self.rest_list = QListWidget()
        self.rest_list.setFixedHeight(150)
        left = QVBoxLayout()
        left.addWidget(QLabel("즐겨찾기 — 첫 줄, 위에서부터 왼쪽→오른쪽 (끌어서 순서 변경)"))
        left.addWidget(self.fav_list)
        mid = QVBoxLayout()
        for text, fn, tip in (("◀ 넣기", self._fav_add, "오른쪽에서 고른 버튼을 즐겨찾기 끝에"),
                              ("빼기 ▶", self._fav_remove, "즐겨찾기에서 빼서 전체 줄로"),
                              ("▲", lambda: self._fav_move(-1), "앞으로"), ("▼", lambda: self._fav_move(1), "뒤로")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            mid.addWidget(b)
        mid.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(QLabel("전체 줄 — 체크하면 이 장소에서 숨김"))
        right.addWidget(self.rest_list)
        brow.addLayout(left, 1)
        brow.addLayout(mid)
        brow.addLayout(right, 1)
        v.addLayout(brow)
        reset_row = QHBoxLayout()
        rb = QPushButton("버튼 막대 기본 배치로 (집·회사 모두)")
        rb.clicked.connect(self._bar_defaults)
        reset_row.addWidget(rb)
        reset_row.addStretch(1)
        v.addLayout(reset_row)
        self._load_bar_lists()
        # --- mail ------------------------------------------------------------------------------
        from ..core.mailcompose import PROVIDERS
        self.has_mail_section = edition.has("mail")      # the work edition has no 메일 button (nor mail_ui): nothing to set
        mail_box = QWidget(self)
        mv = QVBoxLayout(mail_box)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(QLabel("<b>메일</b> — [메일] 버튼이 여는 메일 쓰기 화면. 보내기는 항상 직접 누릅니다."))
        mrow = QHBoxLayout()
        self.mail_provider = QComboBox()
        self.mail_provider.addItem("처음 보낼 때 고르기", "")
        if self.has_mail_section:
            from .mail_ui import ORDER
            for pid in ORDER:
                self.mail_provider.addItem(PROVIDERS[pid].label, pid)
        self.mail_provider.setCurrentIndex(max(0, self.mail_provider.findData(settings.mail_provider)))
        mrow.addWidget(self.mail_provider, 1)
        self.mail_account = QLineEdit(settings.mail_account)
        self.mail_account.setPlaceholderText("Gmail 계정이 여러 개면 보낼 계정 (선택)")
        mrow.addWidget(self.mail_account, 1)
        mv.addLayout(mrow)
        self.mail_custom = QLineEdit(settings.mail_custom_url)
        self.mail_custom.setPlaceholderText("직접 입력: 회사 메일 쓰기 주소 https://… ({to} {cc} {subject} 사용 가능)")
        mv.addWidget(self.mail_custom)
        if self.has_mail_section:
            v.addWidget(mail_box)
        else:
            mail_box.hide()
        # --- AI: translate / summary --------------------------------------------------------
        v.addWidget(QLabel("<b>AI 번역·요약</b> — 번역은 항상 무료·오프라인. 요약 방식을 고르세요."))
        self.has_gemini = edition.has_gemini()            # work: the company AI server instead
        self.ai_local = QRadioButton("요약: 오프라인 AI (PC 안에서 처리 · 무료 · 느림, 처음 한 번 약 1.4GB 받기)")
        self.ai_cloud = QRadioButton("요약: Gemini (Google 무료 AI · 빠르고 정확 · 무료 키 필요, 글이 Google로 전송)"
                                     if self.has_gemini else
                                     "요약: 회사 AI (사내 LLM 서버 · 빠르고 정확 · 글이 설정한 회사 서버로 전송)")
        grp = QButtonGroup(self)
        grp.addButton(self.ai_local)
        grp.addButton(self.ai_cloud)
        (self.ai_cloud if settings.ai_summary_engine == "cloud" else self.ai_local).setChecked(True)
        self.ai_cloud_translate = QCheckBox("번역도 Gemini로 (더 자연스러운 번역, 키가 있을 때)" if self.has_gemini
                                            else "번역도 회사 AI로 (더 자연스러운 번역, 서버·키가 있을 때)")
        self.ai_cloud_translate.setChecked(settings.ai_cloud_translate)
        self._ai_key = settings.ai_key
        self._ai_consent = settings.ai_cloud_consent
        self._ai_endpoint, self._ai_model = settings.ai_endpoint, settings.ai_model
        from ..core.share import EXPIRIES, EXPIRY_NAMES
        self.has_share_section = edition.has_share()      # work: no internet share link, nothing to set
        share_box = QWidget(self)
        share_row = QHBoxLayout(share_box)
        share_row.setContentsMargins(0, 0, 0, 0)
        share_row.addWidget(QLabel("인터넷 공유 링크 보관 시간 (지나면 자동 삭제)"))
        self.share_expiry = QComboBox()
        for code in EXPIRIES:
            self.share_expiry.addItem(EXPIRY_NAMES[code], code)
        self.share_expiry.setCurrentIndex(max(0, self.share_expiry.findData(settings.share_expiry)))
        share_row.addWidget(self.share_expiry)
        share_row.addStretch(1)
        if self.has_share_section:
            v.addWidget(share_box)
        else:
            share_box.hide()
        keyrow = QHBoxLayout()
        self.ai_key_status = QLabel()
        keyrow.addWidget(self.ai_key_status, 1)
        key_btn = QPushButton("무료 키 설정 안내…" if self.has_gemini else "회사 AI 서버·키 설정…")
        key_btn.clicked.connect(self._key_wizard)
        keyrow.addWidget(key_btn)
        for w in (self.ai_local, self.ai_cloud, self.ai_cloud_translate):
            v.addWidget(w)
        v.addLayout(keyrow)
        self._refresh_key()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.Ok).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.RestoreDefaults).setText("기본값 복원")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        outer = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(body)
        outer.addWidget(area, 1)
        outer.addWidget(buttons)
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry().height() if scr is not None else 900
        self.resize(max(640, body.sizeHint().width() + 40), min(body.sizeHint().height() + 80, avail - 80, 940))
        self._show_problems()

    # --- action bar lists ------------------------------------------------------------------------
    def _load_bar_lists(self) -> None:
        from ..core import bar_layout as bl
        from .side_bar import LABELS
        p = self._profiles[self._place]
        avail = set(bl.available_names())
        self.fav_list.clear()
        self.rest_list.clear()
        for n in p.favourites:
            if n in avail:
                it = QListWidgetItem(LABELS.get(n, n))
                it.setData(Qt.UserRole, n)
                self.fav_list.addItem(it)
        for _, label, names in bl.GROUPS:
            rest = [n for n in names if n in avail and n not in p.favourites]
            if not rest:
                continue
            head = QListWidgetItem(f"— {label} —")
            head.setFlags(Qt.NoItemFlags)
            self.rest_list.addItem(head)
            for n in rest:
                it = QListWidgetItem(LABELS.get(n, n))
                it.setData(Qt.UserRole, n)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if n in p.hidden else Qt.Unchecked)
                self.rest_list.addItem(it)

    def _collect_bar(self) -> None:
        from ..core import bar_layout as bl
        fav = [self.fav_list.item(i).data(Qt.UserRole) for i in range(self.fav_list.count())]
        hidden = [self.rest_list.item(i).data(Qt.UserRole) for i in range(self.rest_list.count())
                  if self.rest_list.item(i).data(Qt.UserRole) and self.rest_list.item(i).checkState() == Qt.Checked]
        self._profiles[self._place] = bl.clean({"favourites": fav, "hidden": hidden})

    def _switch_place(self, *_) -> None:
        self._collect_bar()
        self._place = "home" if self.place_home.isChecked() else "work"
        self._load_bar_lists()

    def _bar_edit(self, fn) -> None:
        self._collect_bar()
        self._profiles[self._place] = fn(self._profiles[self._place])
        self._load_bar_lists()

    def _select_fav(self, name: str) -> None:
        for i in range(self.fav_list.count()):
            if self.fav_list.item(i).data(Qt.UserRole) == name:
                self.fav_list.setCurrentRow(i)
                return

    def _fav_add(self) -> None:
        from ..core import bar_layout as bl
        it = self.rest_list.currentItem()
        n = it.data(Qt.UserRole) if it is not None else None
        if n:
            self._bar_edit(lambda p: bl.add_favourite(p, n))
            self._select_fav(n)

    def _fav_remove(self) -> None:
        from ..core import bar_layout as bl
        it = self.fav_list.currentItem()
        n = it.data(Qt.UserRole) if it is not None else None
        if n:
            self._bar_edit(lambda p: bl.remove_favourite(p, n))

    def _fav_move(self, delta: int) -> None:
        from ..core import bar_layout as bl
        it = self.fav_list.currentItem()
        n = it.data(Qt.UserRole) if it is not None else None
        if n:
            self._bar_edit(lambda p: bl.move_favourite(p, n, delta))
            self._select_fav(n)

    def _bar_defaults(self) -> None:
        from ..core import bar_layout as bl
        self._profiles = {p: bl.default_profile(p) for p in bl.WORKPLACES}
        self._load_bar_lists()

    def _refresh_key(self) -> None:
        if self.has_gemini:
            self.ai_key_status.setText("Gemini 키: 설정됨" if self._ai_key else "Gemini 키: 없음 (오프라인으로 동작)")
        elif self._ai_endpoint:
            self.ai_key_status.setText(f"회사 AI: {self._ai_endpoint} · 모델 {self._ai_model or '(없음)'} · "
                                       + ("키 설정됨" if self._ai_key else "키 없음 (오프라인으로 동작)"))
        else:
            self.ai_key_status.setText("회사 AI: 서버 주소 없음 (오프라인으로 동작)")

    def _key_wizard(self) -> None:
        from .ai_ui import KeyDialog
        tmp = Settings(ai_key=self._ai_key, ai_summary_engine="cloud" if self.ai_cloud.isChecked() else "local",
                       ai_cloud_translate=self.ai_cloud_translate.isChecked(),
                       ai_endpoint=self._ai_endpoint, ai_model=self._ai_model)
        KeyDialog(tmp, parent=self).exec()
        self._ai_key = tmp.ai_key
        self._ai_endpoint, self._ai_model = tmp.ai_endpoint, tmp.ai_model
        (self.ai_cloud if tmp.ai_summary_engine == "cloud" else self.ai_local).setChecked(True)
        self.ai_cloud_translate.setChecked(tmp.ai_cloud_translate)
        self._refresh_key()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.save_dir.text())
        if d:
            self.save_dir.setText(d)

    def _defaults(self):
        d = Settings()
        for action, ed in self.edits.items():
            ed.setText(d.hotkeys.get(action, ""))
        self.ppt_new_slide.setChecked(d.ppt_new_slide)
        self.auto_copy.setChecked(d.auto_copy)
        self.show_recent.setChecked(d.show_recent)
        self.update_check.setChecked(d.update_check)
        self.update_source.setText(d.update_source)
        self.pdf_one_page.setChecked(d.pdf_one_page)
        self.keep_style.setChecked(d.keep_style)

    def validate(self) -> list[str]:
        errors: list[str] = []
        parsed = {}
        labels = dict(ACTIONS)
        for action, ed in self.edits.items():
            t = ed.text().strip()
            if not t:
                continue
            try:
                hk = parse(t)
            except HotkeyError as e:
                errors.append(f"{labels[action]}: {e}")
                continue
            if is_reserved(hk):
                errors.append(f"{labels[action]}: {hk} 는 Windows 시스템 단축키라 사용할 수 없습니다.")
                continue
            parsed[action] = hk
        for a, b in find_duplicates(parsed):
            errors.append(f"'{labels[a]}'와 '{labels[b]}' 단축키가 겹칩니다.")
        from ..core.mailcompose import valid_custom
        custom = self.mail_custom.text().strip() if self.has_mail_section else ""
        if (self.mail_provider.currentData() == "custom" or custom) and not valid_custom(custom):
            errors.append("회사 메일 쓰기 주소는 https:// 로 시작해야 합니다. (예: https://mail.회사.com/write)")
        acct = self.mail_account.text().strip()
        if acct:
            from ..core.contacts import is_email
            if not is_email(acct):
                errors.append("메일: Gmail 계정 주소가 올바르지 않습니다.")
        return errors

    def warnings(self) -> list[str]:
        out = []
        for action, ed in self.edits.items():
            try:
                hk = parse(ed.text())
            except HotkeyError:
                continue
            out += [f"{hk}: {m}" for m in known_conflicts(hk)]
        return out

    def _show_problems(self, *_):
        msgs = self.validate() + self.warnings()
        self.problems.setText("\n".join("⚠ " + m for m in msgs))

    def result_settings(self) -> Settings:
        s = copy.deepcopy(self._base)
        s.hotkeys = {a: ed.text().strip() for a, ed in self.edits.items()}
        s.save_dir = self.save_dir.text().strip()
        s.filename_pattern = self.pattern.text().strip() or Settings().filename_pattern
        s.image_format = self.fmt.currentText()
        s.jpg_quality = self.quality.value()
        s.auto_save = self.auto_save.isChecked()
        s.redact_pii = self.redact.isChecked()
        s.launch_at_startup = self.startup.isChecked()
        s.ppt_new_slide = self.ppt_new_slide.isChecked()
        s.auto_copy = self.auto_copy.isChecked()
        s.show_recent = self.show_recent.isChecked()
        s.update_check = self.update_check.isChecked()
        s.update_source = self.update_source.text().strip()
        s.pdf_one_page = self.pdf_one_page.isChecked()
        s.keep_style = self.keep_style.isChecked()
        s.ai_summary_engine = "cloud" if self.ai_cloud.isChecked() else "local"
        s.mail_provider = self.mail_provider.currentData() or ""
        s.mail_account = self.mail_account.text().strip()
        s.mail_custom_url = self.mail_custom.text().strip()
        s.ai_cloud_translate = self.ai_cloud_translate.isChecked()
        s.ai_key = self._ai_key
        s.ai_endpoint, s.ai_model = self._ai_endpoint, self._ai_model
        s.share_expiry = self.share_expiry.currentData()
        from ..core import bar_layout as bl
        self._collect_bar()
        s.workplace = self._place
        for place, p in self._profiles.items():
            bl.store_profile(s, place, p)
        return s

    def _accept(self):
        if self.validate():
            self._show_problems()
            return
        self.accept()
