"""Translate / summarize from the capture UI (fake AI service), key wizard, settings."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.ai_local import Busy, ModelMissing
from capture_tool.core.ai_service import AiResult, ConsentNeeded
from capture_tool.core.clipboard_payload import UNICODE
from capture_tool.core.ocr import OcrLine
from capture_tool.core.settings import Settings
from tests.test_app import FakeOcr, FakePpt, _editing, drag, make  # noqa: F401 (fixture)

LINES = [OcrLine("Quarterly revenue grew.", (10, 10, 200, 20), 0.99),
         OcrLine("담당 010-1234-5678", (10, 40, 200, 20), 0.98)]


class FakeAi:
    def __init__(self, raises=None):
        self.calls, self.raises = [], list(raises or [])
        self.busy = False
        self.unloaded = 0

    def _maybe_raise(self):
        if self.raises:
            e = self.raises.pop(0)
            if e is not None:
                raise e

    def translate(self, text, src=None, tgt=None, cancel=None):
        self.calls.append(("translate", text, src, tgt))
        self._maybe_raise()
        return AiResult(f"<{tgt or 'ko'}>{text}", "local", src or "en", tgt or "ko", "")

    def summarize(self, text, lang="ko", on_text=None, cancel=None):
        self.calls.append(("summarize", text, lang))
        self._maybe_raise()
        if on_text:
            on_text("• 부분")
        return AiResult("• 매출 증가", "cloud", tgt=lang, note="")

    def unload(self):
        self.unloaded += 1


def text_mode(make, ai=None, **kw):
    c, ov = _editing(make, ocr=FakeOcr(LINES), **kw)
    c.ai = ai or FakeAi()
    ov.side_bar.trigger("text")
    return c, ov


def test_AAPP_01_text_mode_has_translate_and_summary_buttons(make):
    c, ov = text_mode(make)
    assert {"translate", "summarize"} <= set(ov.ocr_bar.buttons)
    ov.ocr_bar.trigger("translate")
    win = c.ai_window
    assert win is not None and win.isVisible() and win.mode == "translate"
    assert win.result_text().startswith("<ko>Quarterly revenue grew.")
    assert c.overlays                                          # the capture stays open


def test_AAPP_02_only_the_dragged_part_is_translated(make):
    c, ov = text_mode(make)
    drag(ov, (100 + 5, 100 + 5), (100 + 215, 100 + 32))       # first line only
    ov.ocr_bar.trigger("translate")
    assert c.ai.calls[-1][1] == "Quarterly revenue grew."


def test_AAPP_03_summary_streams_then_shows_result_and_engine(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("summarize")
    win = c.ai_window
    assert win.mode == "summarize" and win.result_text() == "• 매출 증가"
    assert "Gemini" in win.status_text()


def test_AAPP_04_copy_and_ppt_from_the_result(make):
    from capture_tool.platform.powerpoint import TextItem
    c, ov = text_mode(make)
    c.powerpoint = FakePpt()
    ov.ocr_bar.trigger("translate")
    c.ai_window.trigger("copy")
    assert c.clipboard.last[UNICODE].startswith("<ko>")
    c.ai_window.trigger("ppt")
    assert isinstance(c.powerpoint.items[-1], TextItem) and c.powerpoint.items[-1].text.startswith("<ko>")


def test_AAPP_05_change_target_language_translates_again(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("translate")
    c.ai_window.set_target("ja")
    assert c.ai.calls[-1][3] == "ja" and c.ai_window.result_text().startswith("<ja>")


def test_AAPP_06_missing_model_asks_downloads_and_retries(make):
    c, ov = text_mode(make, ai=FakeAi(raises=[ModelMissing(["mt-en_ko"]), None]))
    asked, got = [], []
    c.ask_yes_no = lambda title, text: asked.append(text) or True
    c.download_packs = lambda packs, done: (got.append(packs), done(True))
    ov.ocr_bar.trigger("translate")
    assert asked and "MB" in asked[0] and got == [["mt-en_ko"]]
    assert c.ai_window.result_text().startswith("<ko>")


def test_AAPP_07_missing_model_declined(make):
    c, ov = text_mode(make, ai=FakeAi(raises=[ModelMissing(["llm-qwen3-1.7b"])]))
    c.ask_yes_no = lambda title, text: False
    ov.ocr_bar.trigger("summarize")
    assert "받지 않" in c.ai_window.status_text() and c.ai_window.result_text() == ""


def test_AAPP_08_cloud_consent_asked_once_and_saved(make):
    c, ov = text_mode(make, ai=FakeAi(raises=[ConsentNeeded(), None]))
    shown = []
    c.ask_consent = lambda: shown.append(1) or "agree"
    ov.ocr_bar.trigger("summarize")
    assert shown and c.settings.ai_cloud_consent is True
    assert c.ai_window.result_text() == "• 매출 증가"


def test_AAPP_09_consent_refused_runs_offline_this_time(make):
    c, ov = text_mode(make, ai=FakeAi(raises=[ConsentNeeded(), None]))
    c.ask_consent = lambda: "offline"
    ov.ocr_bar.trigger("summarize")
    assert c.settings.ai_cloud_consent is False
    assert c.ai_offline_once_used is True and c.ai_window.result_text() == "• 매출 증가"


def test_AAPP_10_busy_is_reported(make):
    c, ov = text_mode(make, ai=FakeAi(raises=[Busy("번역·요약을 하는 중입니다.")]))
    ov.ocr_bar.trigger("translate")
    assert "하는 중" in c.ai_window.status_text()


def test_AAPP_11_no_text_no_window(make):
    c, ov = _editing(make, ocr=FakeOcr([]))
    c.ai = FakeAi()
    c.on_ocr_action("translate")
    assert c.ai.calls == [] and c.ai_window is None


def test_AAPP_12_escape_closes_the_result_window_only(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("translate")
    QTest.keyClick(c.ai_window, Qt.Key_Escape)
    assert not c.ai_window.isVisible() and c.overlays


def test_AAPP_13_text_window_has_translate_and_summary(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("window")
    panel = c.text_panel
    panel.buttons["summarize"].click()
    assert c.ai.calls[-1][0] == "summarize" and c.ai_window.isVisible()


def test_AAPP_14_models_are_freed_after_idle(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("translate")
    c.ai_idle()                                              # what the idle timer calls
    assert c.ai.unloaded == 1


# --- key wizard ---------------------------------------------------------------------------------------
KEY = "AIza" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"


def test_KEY_01_copied_key_is_found_tested_and_saved_encrypted(qt_app):
    from capture_tool.app.ai_ui import KeyDialog
    s = Settings()
    opened, checked = [], []
    dlg = KeyDialog(s, open_url=opened.append, check=lambda k: checked.append(k), sync=True)
    dlg.buttons["open"].click()
    assert opened and "aistudio.google.com" in opened[0]
    dlg.on_clipboard(f"  {KEY}\n")
    assert checked == [KEY] and dlg.ok
    assert KEY not in dlg.key_label.text() and "AIza" in dlg.key_label.text()   # shown masked
    dlg.save()
    assert s.ai_key and KEY not in s.ai_key and s.ai_summary_engine == "cloud"
    from capture_tool.platform.secret import unprotect
    assert unprotect(s.ai_key) == KEY


def test_KEY_02_wrong_key_is_not_saved(qt_app):
    from capture_tool.app.ai_ui import KeyDialog
    from capture_tool.core.gemini import GeminiError
    s = Settings()

    def bad(k):
        raise GeminiError("key")
    dlg = KeyDialog(s, open_url=lambda u: None, check=bad, sync=True)
    dlg.on_clipboard(KEY)
    assert not dlg.ok and "올바르지" in dlg.status.text()
    assert not dlg.buttons["save"].isEnabled()


def test_KEY_03_other_clipboard_text_is_ignored_and_manual_paste_works(qt_app):
    from capture_tool.app.ai_ui import KeyDialog
    s = Settings()
    checked = []
    dlg = KeyDialog(s, open_url=lambda u: None, check=checked.append, sync=True)
    dlg.on_clipboard("그냥 복사한 글")
    assert checked == []
    dlg.manual.setText(KEY)
    dlg.buttons["test"].click()
    assert checked == [KEY]


def test_KEY_04_remove_key(qt_app):
    from capture_tool.app.ai_ui import KeyDialog
    from capture_tool.platform.secret import protect
    s = Settings(ai_key=protect(KEY), ai_summary_engine="cloud", ai_cloud_translate=True)
    dlg = KeyDialog(s, open_url=lambda u: None, check=lambda k: None, sync=True)
    dlg.remove()
    assert s.ai_key == "" and s.ai_summary_engine == "local" and not s.ai_cloud_translate


def test_KEY_05_settings_dialog_ai_section(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings())
    assert dlg.ai_local.isChecked() and not dlg.ai_cloud.isChecked()
    assert "없음" in dlg.ai_key_status.text()
    dlg.ai_cloud.setChecked(True)
    dlg.ai_cloud_translate.setChecked(True)
    s = dlg.result_settings()
    assert s.ai_summary_engine == "cloud" and s.ai_cloud_translate


# --- v0.4.1: visible feedback -------------------------------------------------------------------------
def test_AAPP_15_ppt_from_result_window_shows_progress_then_gets_out_of_the_way(make):
    from capture_tool.platform.powerpoint import TextItem
    c, ov = text_mode(make)
    c.powerpoint = FakePpt()
    ov.ocr_bar.trigger("summarize")
    win = c.ai_window
    win.trigger("ppt")
    assert isinstance(c.powerpoint.items[-1], TextItem)
    assert "PowerPoint" in win.status_text() and "넣었습니다" in win.status_text()
    assert c.overlays == [] and not win.isVisible()          # PowerPoint (new slide) is now visible


def test_AAPP_16_ppt_failure_is_shown_in_the_window_which_stays(make):
    c, ov = text_mode(make)
    c.powerpoint = FakePpt(ok=False)
    ov.ocr_bar.trigger("summarize")
    win = c.ai_window
    win.trigger("ppt")
    assert win.isVisible() and "설치" in win.status_text()
    assert win.buttons["ppt"].isEnabled()                    # can try again


def test_AAPP_17_ppt_clicked_again_while_sending_is_ignored(make):
    c, ov = text_mode(make)
    ppt = FakePpt()
    ppt.busy = True
    c.powerpoint = ppt
    ov.ocr_bar.trigger("summarize")
    c.ai_window.trigger("ppt")
    assert ppt.calls == 0 and "보내는 중" in c.ai_window.status_text()


def test_AAPP_18_copy_result_confirms_in_the_window(make):
    c, ov = text_mode(make)
    ov.ocr_bar.trigger("translate")
    c.ai_window.trigger("copy")
    assert "복사했습니다" in c.ai_window.status_text()


def test_TP_01_text_window_shows_what_was_copied(qt_app):
    from capture_tool.app.text_panel import TextPanel
    from capture_tool.core.clipboard_payload import HTML
    got = []
    lines = [OcrLine("품목", (10, 10, 40, 20), 0.9), OcrLine("수량", (200, 10, 40, 20), 0.9),
             OcrLine("사과", (10, 40, 40, 20), 0.9), OcrLine("3", (200, 40, 10, 20), 0.9)]
    p = TextPanel(lines, got.append, redact=False)
    p.copy_table()
    assert HTML in got[-1] and "표 2행×2열" in p.status.text()
    p.copy_all()
    assert "전체" in p.status.text() and "복사" in p.status.text()
    p.close()


def test_TP_02_table_copy_with_no_table_says_so(qt_app):
    from capture_tool.app.text_panel import TextPanel
    got = []
    p = TextPanel([], got.append, redact=False)
    p.copy_table()
    assert got == [] and "없습니다" in p.status.text()
    p.close()


def test_TOAST_01_toast_shows_message_and_hides_itself(qt_app):
    from capture_tool.app.toast import Toast
    t = Toast()
    t.show_message("결과를 PowerPoint에 넣었습니다.")
    assert t.isVisible() and "PowerPoint" in t.label.text()
    t.show_message("두 번째")
    assert t.label.text() == "두 번째"                     # replaces, doesn't stack
    t._timer.timeout.emit()
    assert not t.isVisible()
    assert t.testAttribute(Qt.WA_ShowWithoutActivating)   # never steals focus from the capture



def test_AAPP_19_powerpoint_is_brought_to_the_front_after_inserting(make):
    c, ov = text_mode(make)
    ppt = FakePpt()
    ppt.last_hwnd = 777
    c.powerpoint = ppt
    shown = []
    c.bring_to_front = shown.append
    ov.ocr_bar.trigger("summarize")
    c.ai_window.trigger("ppt")
    assert shown == [777]


def test_AAPP_20_capture_ppt_button_also_brings_powerpoint_forward(make):
    c, ov = _editing(make)
    ppt = FakePpt()
    ppt.last_hwnd = 778
    c.powerpoint = ppt
    shown = []
    c.bring_to_front = shown.append
    ov.side_bar.trigger("ppt")
    assert shown == [778]


def test_AAPP_21_failed_insert_does_not_switch_windows(make):
    c, ov = _editing(make)
    c.powerpoint = FakePpt(ok=False)
    shown = []
    c.bring_to_front = shown.append
    ov.side_bar.trigger("ppt")
    assert shown == []


def test_AAPP_22_models_start_loading_when_text_mode_opens(make):
    class PreAi(FakeAi):
        def __init__(self):
            super().__init__()
            self.preloaded = []

        def preload(self, text):
            self.preloaded.append(text)
    ai = PreAi()
    c, ov = _editing(make, ocr=FakeOcr(LINES))
    c.ai = ai
    ov.side_bar.trigger("text")
    assert ai.preloaded and "Quarterly" in ai.preloaded[0]


def test_AAPP_23_preload_never_breaks_text_mode(make):
    class Broken(FakeAi):
        def preload(self, text):
            raise RuntimeError("model file damaged")
    c, ov = _editing(make, ocr=FakeOcr(LINES))
    c.ai = Broken()
    ov.side_bar.trigger("text")
    assert ov.ocr_lines is not None
