"""Translate / summary result window, first-use consent, and the Gemini key wizard."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..core.ai_text import LANGS, NAMES_KO
from ..core.gemini import KEY_PAGE, GeminiError, find_key

ENGINE = {"local": "오프라인 AI (PC 안에서 처리)", "cloud": "Gemini (Google 무료 AI)"}


class AiWindow(QWidget):
    action = Signal(str)            # copy, ppt, cancel
    targetChanged = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.mode = "translate"
        self.resize(460, 380)
        v = QVBoxLayout(self)
        self.title = QLabel()
        v.addWidget(self.title)
        row = QHBoxLayout()
        self.lang_label = QLabel("번역할 언어")
        row.addWidget(self.lang_label)
        self.target = QComboBox()
        for code in LANGS:
            self.target.addItem(NAMES_KO[code], code)
        self.target.activated.connect(lambda i: self.targetChanged.emit(self.target.itemData(i)))
        row.addWidget(self.target)
        row.addStretch(1)
        v.addLayout(row)
        self.edit = QPlainTextEdit()
        v.addWidget(self.edit, 1)
        self.progress = QProgressBar()
        self.progress.hide()
        v.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        btns = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for name, label in [("copy", "복사"), ("ppt", "PPT로"), ("cancel", "중지"), ("close", "닫기 (Esc)")]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name: self.trigger(n))
            btns.addWidget(b)
            self.buttons[name] = b
        v.addLayout(btns)

    # --- state ------------------------------------------------------------------------------------
    def start(self, mode: str, tgt: str | None = None) -> None:
        self.mode = mode
        is_tr = mode == "translate"
        self.setWindowTitle("번역" if is_tr else "요약")
        self.title.setText("<b>번역</b>" if is_tr else "<b>요약</b>")
        for w in (self.lang_label, self.target):
            w.setVisible(is_tr)
        if tgt:
            self.target.setCurrentIndex(max(0, self.target.findData(tgt)))
        self.edit.setPlainText("")
        self.set_busy("번역하는 중…" if is_tr else "요약하는 중…")

    def set_busy(self, text: str) -> None:
        self.status.setText(text)
        self.buttons["cancel"].setEnabled(True)

    def set_partial(self, text: str) -> None:
        self.edit.setPlainText(text)

    def set_result(self, result) -> None:
        self.edit.setPlainText(result.text)
        if result.tgt and self.mode == "translate":
            self.target.setCurrentIndex(max(0, self.target.findData(result.tgt)))
        msg = ENGINE.get(result.engine, result.engine)
        self.set_status(msg + (" · " + result.note if result.note else ""))

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.buttons["cancel"].setEnabled(False)
        self.progress.hide()

    def show_progress(self, done: int, total: int) -> None:
        self.progress.show()
        self.progress.setMaximum(max(1, total // 1024))
        self.progress.setValue(done // 1024)
        self.status.setText(f"AI 모델 받는 중… {done / 2**20:,.0f} / {total / 2**20:,.0f} MB")

    def result_text(self) -> str:
        return self.edit.toPlainText()

    def status_text(self) -> str:
        return self.status.text()

    def set_target(self, code: str) -> None:
        self.target.setCurrentIndex(max(0, self.target.findData(code)))
        self.targetChanged.emit(code)

    def trigger(self, name: str) -> None:
        if name == "close":
            self.close()
        else:
            self.action.emit(name)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)


CONSENT_TEXT = (
    "Gemini(Google의 무료 AI)를 쓰면 인식한 글이 <b>Google 서버로 전송</b>됩니다.<br><br>"
    "• 무료 등급에서는 Google이 품질 개선을 위해 <b>사람이 내용을 볼 수 있습니다</b>.<br>"
    "• 회사 기밀·개인정보가 담긴 글은 보내지 마세요.<br>"
    "• 전화번호·이메일·주민번호·카드번호는 보내기 전에 자동으로 가립니다.<br><br>"
    "동의하면 다음부터는 묻지 않습니다(설정 → AI에서 언제든 끌 수 있습니다).")


def ask_consent(parent=None) -> str:
    box = QMessageBox(parent)
    box.setWindowTitle("Gemini 사용 동의")
    box.setTextFormat(Qt.RichText)
    box.setText(CONSENT_TEXT)
    agree = box.addButton("동의하고 사용", QMessageBox.AcceptRole)
    offline = box.addButton("이번엔 오프라인으로", QMessageBox.RejectRole)
    box.addButton("취소", QMessageBox.DestructiveRole)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    box.exec()
    return "agree" if box.clickedButton() is agree else "offline" if box.clickedButton() is offline else "cancel"


def ask_yes_no(title: str, text: str, parent=None) -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    return box.exec() == QMessageBox.Yes


# --- key wizard ------------------------------------------------------------------------------------------
class _Signals(QObject):
    done = Signal(object)


class _Run(QRunnable):
    def __init__(self, fn, sig):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self):
        try:
            self.fn()
            self.sig.done.emit(None)
        except Exception as e:  # noqa: BLE001 - shown in the dialog
            self.sig.done.emit(e)


def masked_key(key: str) -> str:
    return key[:4] + "•" * 8 + key[-4:]


class KeyDialog(QDialog):
    """Three steps: open the key page → copy the key there → the app notices, tests, saves."""

    def __init__(self, settings, open_url=None, check=None, sync: bool = False, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.open_url = open_url or self._open
        self.check = check or (lambda k: __import__("capture_tool.core.gemini", fromlist=["Gemini"]).Gemini(k).check())
        self.sync = sync
        self.key: str | None = None
        self.ok = False
        self.setWindowTitle("Gemini 무료 키 설정")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "<b>빠른 요약·자연스러운 번역을 위한 Google Gemini 무료 키 설정 (약 1분)</b><br><br>"
            "① 아래 버튼을 눌러 키 발급 페이지를 엽니다. (Google 계정으로 로그인)<br>"
            "② 페이지에서 <b>'API 키 만들기(Create API key)'</b>를 누르고, 만들어진 키 옆의 <b>복사</b>를 누릅니다.<br>"
            "③ 복사하면 이 창이 <b>자동으로 알아보고</b> 연결을 확인합니다. 그다음 <b>저장</b>을 누르세요.<br><br>"
            "<small>키는 이 PC의 내 Windows 계정으로 암호화해 저장합니다. 무료이며 카드 등록이 필요 없습니다. "
            "만 18세 이상만 사용할 수 있습니다.</small>"))
        self.buttons: dict[str, QPushButton] = {}
        open_b = QPushButton("① 키 발급 페이지 열기")
        open_b.clicked.connect(lambda: self.open_url(KEY_PAGE))
        self.buttons["open"] = open_b
        v.addWidget(open_b)
        self.key_label = QLabel("키를 기다리는 중… (복사하면 자동으로 들어옵니다)")
        v.addWidget(self.key_label)
        row = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("자동으로 안 되면 여기에 붙여넣기 (Ctrl+V)")
        self.manual.setEchoMode(QLineEdit.Password)
        row.addWidget(self.manual, 1)
        test = QPushButton("확인")
        test.clicked.connect(lambda: self.on_clipboard(self.manual.text()))
        self.buttons["test"] = test
        row.addWidget(test)
        v.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        btns = QHBoxLayout()
        for name, label, fn in [("save", "저장", self.save), ("remove", "키 지우기", self.remove),
                                ("close", "닫기", self.reject)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
            self.buttons[name] = b
        self.buttons["save"].setEnabled(False)
        self.buttons["remove"].setEnabled(bool(settings.ai_key))
        v.addLayout(btns)
        self._sig = _Signals()
        self._sig.done.connect(self._checked)
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.dataChanged.connect(lambda: self.isVisible() and self.on_clipboard(cb.text()))

    @staticmethod
    def _open(url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def on_clipboard(self, text: str) -> None:
        key = find_key(text or "")
        if not key or key == self.key and self.ok:
            return
        self.key, self.ok = key, False
        self.key_label.setText(f"찾은 키: {masked_key(key)}")
        self.status.setText("연결을 확인하는 중…")
        self.buttons["save"].setEnabled(False)
        if self.sync:
            try:
                self.check(key)
                self._checked(None)
            except Exception as e:  # noqa: BLE001
                self._checked(e)
        else:
            QThreadPool.globalInstance().start(_Run(lambda: self.check(key), self._sig))

    def _checked(self, error) -> None:
        if error is None:
            self.ok = True
            self.status.setText("연결됐습니다. 저장을 누르세요.")
            self.buttons["save"].setEnabled(True)
        elif isinstance(error, GeminiError) and error.kind == "quota":
            self.ok = True       # the key works; today's free quota is just used up
            self.status.setText("키는 맞습니다. 오늘 무료 한도를 다 써서 내일부터 빠르게 쓸 수 있습니다. 저장을 누르세요.")
            self.buttons["save"].setEnabled(True)
        else:
            self.ok = False
            self.status.setText(str(error) if isinstance(error, GeminiError)
                                else f"확인하지 못했습니다: {error}")

    def save(self) -> None:
        if not (self.ok and self.key):
            return
        from ..platform.secret import protect
        self.settings.ai_key = protect(self.key)
        self.settings.ai_summary_engine = "cloud"
        self.accept()

    def remove(self) -> None:
        self.settings.ai_key = ""
        self.settings.ai_summary_engine = "local"
        self.settings.ai_cloud_translate = False
        self.key, self.ok = None, False
        self.key_label.setText("키를 지웠습니다.")
        self.buttons["remove"].setEnabled(False)
