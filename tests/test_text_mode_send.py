"""BUG-101: in text mode the text was copied, but 메일 (and 카톡) put the PICTURE on the clipboard
again - pasting into the mail gave an image. In text mode they hand over the text, like PPT does."""
from capture_tool.core import contacts as C
from capture_tool.core.clipboard_payload import HTML, PNG, UNICODE
from capture_tool.core.ocr import OcrLine
from tests.test_app import FakeOcr, drag, make  # noqa: F401 (fixture)
from tests.test_kakao import FakeKakao

LINES = [OcrLine("회의는 수요일 오후 세 시", (10, 10, 240, 22), 0.99), OcrLine("장소는 3층 회의실", (10, 44, 180, 22), 0.98)]


def ready(make, tmp_path, text=True):
    from capture_tool.app.mail_ui import MailChoice
    c = make(ocr=FakeOcr(LINES))
    c.contacts_path = tmp_path / "contacts.dat"
    c.protect, c.unprotect = (lambda s: "ENC:" + s[::-1]), (lambda s: s[4:][::-1])
    c.settings.mail_provider = "daum"
    c.open_url = lambda u: True
    c.ask_mail = lambda book, settings, parent=None: MailChoice(["boss@corp.com"], [], "daum")
    c.address_book().add("팀장님", "boss@corp.com")
    c.kakao = FakeKakao()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    if text:
        ov.side_bar.trigger("text")
    return c, ov


def test_TSEND_01_mail_in_text_mode_hands_over_the_text(make, tmp_path):
    c, ov = ready(make, tmp_path)
    c.on_toolbar_action("mail")
    h = c.mail_helper
    assert h is not None and "글자" in h.buttons["capture"].text()
    h.buttons["capture"].click()
    last = c.clipboard.last
    assert "회의는 수요일 오후 세 시" in last.get(UNICODE, "") and PNG not in last, list(last)
    assert HTML in last                                          # with its look, for the mail editor


def test_TSEND_02_mail_right_after_text_copy_never_puts_the_picture_back(make, tmp_path):
    c, ov = ready(make, tmp_path)
    c.on_toolbar_action("mail")
    after_text = c.clipboard.payloads[next(i for i, p in enumerate(c.clipboard.payloads) if "회의는" in str(p.get(UNICODE, ""))):]
    assert not any(PNG in p for p in after_text), [list(p) for p in after_text]
    assert "글자" in c.messages[-1], c.messages[-1]


def test_TSEND_03_mail_outside_text_mode_is_still_the_picture(make, tmp_path):
    c, ov = ready(make, tmp_path, text=False)
    c.on_toolbar_action("mail")
    h = c.mail_helper
    assert "캡처" in h.buttons["capture"].text()
    h.buttons["capture"].click()
    assert PNG in c.clipboard.last


def test_TSEND_04_a_dragged_part_is_what_goes_to_the_mail(make, tmp_path):
    c, ov = ready(make, tmp_path)
    drag(ov, (100 + 10, 100 + 12), (100 + 250, 100 + 30))
    part = c.clipboard.last[UNICODE]
    assert part.strip() and "장소" not in part
    c.on_toolbar_action("mail")
    c.mail_helper.buttons["capture"].click()
    assert c.clipboard.last[UNICODE] == part and PNG not in c.clipboard.last


def test_TSEND_05_kakao_in_text_mode_pastes_the_text(make, tmp_path):
    c, ov = ready(make, tmp_path)
    c.on_toolbar_action("kakao_chat:101")
    assert c.kakao.pasted == [101]
    assert "회의는 수요일 오후 세 시" in c.clipboard.last.get(UNICODE, "") and PNG not in c.clipboard.last
    assert "글자" in c.messages[-1], c.messages[-1]


def test_TSEND_06_kakao_outside_text_mode_is_still_the_picture(make, tmp_path):
    c, ov = ready(make, tmp_path, text=False)
    c.on_toolbar_action("kakao_chat:101")
    assert PNG in c.clipboard.last and "캡처" in c.messages[-1]


def test_TSEND_07_personal_data_stays_hidden_in_the_mail_text(make, tmp_path):
    from capture_tool.app.mail_ui import MailChoice
    c = make(ocr=FakeOcr([OcrLine("연락처 010-1234-5678", (10, 10, 220, 22), 0.99)]))
    c.contacts_path = tmp_path / "contacts.dat"
    c.protect, c.unprotect = (lambda s: "ENC:" + s[::-1]), (lambda s: s[4:][::-1])
    c.open_url = lambda u: True
    c.ask_mail = lambda book, settings, parent=None: MailChoice(["boss@corp.com"], [], "daum")
    c.address_book().add("팀장님", "boss@corp.com")
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.side_bar.trigger("text")
    c.on_toolbar_action("mail")
    c.mail_helper.buttons["capture"].click()
    assert "1234" not in c.clipboard.last[UNICODE]
    assert "1234" not in c.clipboard.last[HTML].decode("utf-8", "replace").split("<!--StartFragment-->")[-1]
