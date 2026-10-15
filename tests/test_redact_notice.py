"""BUG-109: a resident number pasted as ************** looked like a password field. Masking is
the 개인정보 자동 가림 setting; every copy path now says what was masked and how to turn it off,
and the switch in the text window is remembered."""
from capture_tool.core.clipboard_payload import UNICODE
from capture_tool.core.ocr import OcrLine
from capture_tool.core.redact import describe, mask
from capture_tool.core.settings import Settings
from tests.test_app import FakeOcr, drag, make  # noqa: F401 (fixture)

RRN = [OcrLine("주민 020930-3655116", (10, 40, 180, 20), 0.98)]


def _text_mode(make, **kw):
    c = make(**kw)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.toolbar.trigger("text")
    return c, ov


def test_RDN_01_describe_names_what_was_found():
    assert describe("주민 020930-3655116") == "주민번호 1건"
    assert describe("010-1234-5678 / kim@corp.com / 010-9999-8888") == "전화번호 2건·이메일 1건"
    assert describe("아무 숫자 12345") == ""
    assert mask("020930-3655116") == "**************"


def test_RDN_02_text_copy_says_what_was_masked_and_how_to_turn_it_off(make):
    c, ov = _text_mode(make, ocr=FakeOcr(RRN))
    assert "**************" in c.clipboard.last[UNICODE]
    msg = c.messages[-1]
    assert "주민번호 1건" in msg and "*" in msg and "개인정보 자동 가림" in msg


def test_RDN_03_with_the_setting_off_the_digits_are_copied(make):
    c, ov = _text_mode(make, ocr=FakeOcr(RRN), settings=Settings(redact_pii=False))
    assert "020930-3655116" in c.clipboard.last[UNICODE]
    assert "가렸" not in c.messages[-1]


def test_RDN_04_oneline_and_selection_copies_say_so_too(make):
    c, ov = _text_mode(make, ocr=FakeOcr(RRN))
    c.on_ocr_action("oneline")
    assert "주민번호 1건" in c.messages[-1]
    c.copy_ocr_selection((0, 0, 400, 100))
    assert "주민번호 1건" in c.messages[-1] and "*" in c.clipboard.last[UNICODE]


def test_RDN_05_switch_in_the_text_window_is_remembered(make):
    from capture_tool.app.text_panel import TextPanel
    c = make(ocr=FakeOcr(RRN))
    got = []
    p = TextPanel(RRN, c._set_clipboard, True, None, c.notify, None, on_redact=got.append)
    p.redact.setChecked(False)
    assert got == [False] and "020930-3655116" in p.edit.toPlainText()
    c.set_redact(False)
    assert c.settings.redact_pii is False
    assert '"redact_pii": false' in c.settings_path.read_text(encoding="utf-8")
    p.close()


def test_RDN_06_table_copy_from_the_text_bar_says_so(make):
    lines = [OcrLine("이름", (10, 10, 40, 20), 0.98), OcrLine("주민번호", (120, 10, 60, 20), 0.98),
             OcrLine("김민수", (10, 40, 40, 20), 0.98), OcrLine("020930-3655116", (120, 40, 110, 20), 0.98),
             OcrLine("이영희", (10, 70, 40, 20), 0.98), OcrLine("950101-2345678", (120, 70, 110, 20), 0.98)]
    c, ov = _text_mode(make, ocr=FakeOcr(lines))
    c._copy_text(lines, grid=[["이름", "주민번호"], ["김민수", "020930-3655116"], ["이영희", "950101-2345678"]])
    assert "주민번호 2건" in c.messages[-1]
