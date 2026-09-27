"""Settings: record hotkeys by pressing them, save folder, file naming, format, startup."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

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
        v = QVBoxLayout(self)
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
        self.pattern.setToolTip("{date} 날짜, {time} 시간, {datetime} 날짜_시간")
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
        self.auto_save = QCheckBox("복사할 때 자동으로 폴더에도 저장")
        self.auto_save.setChecked(settings.auto_save)
        self.redact = QCheckBox("텍스트 복사 시 개인정보 자동 가림")
        self.redact.setChecked(settings.redact_pii)
        self.startup = QCheckBox("Windows 시작 시 자동 실행")
        self.startup.setChecked(settings.launch_at_startup)
        self.ppt_new_slide = QCheckBox("PPT로 보낼 때 새 슬라이드에 넣기 (끄면 보고 있는 슬라이드에)")
        self.ppt_new_slide.setChecked(settings.ppt_new_slide)
        for w in (self.auto_save, self.redact, self.startup, self.ppt_new_slide):
            v.addWidget(w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.Ok).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.RestoreDefaults).setText("기본값 복원")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        v.addWidget(buttons)
        self._show_problems()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.save_dir.text())
        if d:
            self.save_dir.setText(d)

    def _defaults(self):
        d = Settings()
        for action, ed in self.edits.items():
            ed.setText(d.hotkeys.get(action, ""))
        self.ppt_new_slide.setChecked(d.ppt_new_slide)

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
        return s

    def _accept(self):
        if self.validate():
            self._show_problems()
            return
        self.accept()
