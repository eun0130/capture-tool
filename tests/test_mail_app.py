"""메일 button: pick recipients (address book, groups, new addresses), open the chosen mail
service's compose page in the person's browser, and the paste helper hands over each piece.
Nothing is ever sent by the app."""
import pytest

from capture_tool.core import contacts as C
from capture_tool.core.clipboard_payload import PNG, UNICODE
from tests.test_app import drag, make  # noqa: F401 (fixture)


def fake_protect(s):
    return "ENC:" + s[::-1]


def fake_unprotect(s):
    if not s.startswith("ENC:"):
        raise C.SecretError("no")
    return s[4:][::-1]


@pytest.fixture
def mail(make, tmp_path):
    def build(choice=None, open_ok=True, provider="daum"):
        from capture_tool.app.mail_ui import MailChoice
        c = make()
        c.contacts_path = tmp_path / "contacts.dat"
        c.protect, c.unprotect = fake_protect, fake_unprotect
        c.settings.mail_provider = provider
        opened = []

        def open_url(u):
            opened.append(u)
            return open_ok
        c.open_url = open_url
        asked = []

        def ask(book, settings, parent=None):
            asked.append(book)
            return choice if choice is not None else MailChoice(["boss@corp.com"], ["group:우리 팀"], provider)
        c.ask_mail = ask
        b = c.address_book()
        b.add("팀장님", "boss@corp.com")
        b.add_group("우리 팀", ["a@corp.com", "b@corp.com"])
        c.start_capture()
        drag(c.overlays[0], (100, 100), (500, 400))
        return c, opened, asked
    return build


def test_MAPP_01_mail_opens_compose_and_shows_the_helper(mail):
    c, opened, asked = mail()
    c.on_toolbar_action("mail")
    assert c.overlays == [] and asked                                   # capture closed, picker shown
    assert opened == ["https://mail.daum.net/"]           # a service without prefill: helper does it
    h = c.mail_helper
    assert h is not None and h.isVisible()
    assert h.buttons["to"].text().startswith("① 받는 사람 복사 (1명)") and h.buttons["cc"].text().startswith("② 참조 복사 (2명)")
    h.buttons["to"].click()
    assert c.clipboard.last[UNICODE] == "boss@corp.com" and "✓" in h.buttons["to"].text()
    h.buttons["cc"].click()
    assert c.clipboard.last[UNICODE] == "a@corp.com, b@corp.com"
    h.buttons["subject"].click()
    assert c.clipboard.last[UNICODE].startswith("캡처 공유 — ")
    h.buttons["capture"].click()
    assert PNG in c.clipboard.last


def test_MAPP_02_gmail_is_prefilled_and_helper_says_so(mail):
    from capture_tool.app.mail_ui import MailChoice
    c, opened, _ = mail(MailChoice(["boss@corp.com"], [], "gmail"), provider="gmail")
    c.on_toolbar_action("mail")
    assert opened[0].startswith("https://mail.google.com/mail/?view=cm") and "boss@corp.com" in opened[0]
    assert "이미 채워" in c.mail_helper.hint.text()
    assert c.mail_helper.buttons["cc"].isHidden()                       # no Cc: no Cc button


def test_MAPP_03_cancelled_picker_keeps_the_copy_and_opens_nothing(mail):
    c, opened, _ = mail()
    c.ask_mail = lambda book, settings, parent=None: None
    c.on_toolbar_action("mail")
    assert opened == [] and c.mail_helper is None and PNG in c.clipboard.last


def test_MAPP_04_browser_failure_is_reported_and_helper_still_works(mail):
    c, opened, _ = mail(open_ok=False)
    c.on_toolbar_action("mail")
    assert any("브라우저" in m for m in c.messages)
    assert c.mail_helper is not None


def test_MAPP_05_used_addresses_are_remembered_encrypted(mail):
    c, _, _ = mail()
    c.on_toolbar_action("mail")
    raw = c.contacts_path.read_text(encoding="utf-8")
    assert "boss@corp.com" not in raw
    back, warn = C.load(c.contacts_path, unprotect=fake_unprotect)
    assert back.recent[0] in ("boss@corp.com", "a@corp.com", "b@corp.com") and warn == ""


def test_MAPP_06_new_address_typed_in_the_picker_is_added_to_the_book(mail):
    from capture_tool.app.mail_ui import MailChoice
    c, _, _ = mail(MailChoice(["new.person@x.com"], [], "daum", new={"new.person@x.com": "새 사람"}))
    c.on_toolbar_action("mail")
    assert c.address_book().get("new.person@x.com").name == "새 사람"


def test_MAPP_07_save_for_attachment_when_paste_is_blocked(mail, tmp_path):
    c, _, _ = mail()
    c.settings.save_dir = str(tmp_path / "out")
    c.on_toolbar_action("mail")
    shown = []
    c.reveal_file = shown.append
    c.mail_helper.buttons["file"].click()
    assert shown and shown[0].exists() and shown[0].suffix == ".png"


def test_MAPP_08_custom_service_with_a_bad_address_is_refused_with_a_message(mail):
    from capture_tool.app.mail_ui import MailChoice
    c, opened, _ = mail(MailChoice(["boss@corp.com"], [], "custom"), provider="custom")
    c.settings.mail_custom_url = "javascript:alert(1)"
    c.on_toolbar_action("mail")
    assert opened == [] and any("메일 쓰기 주소" in m for m in c.messages)


def test_MAPP_09_unreadable_address_book_warns_once_and_starts_empty(make, tmp_path):
    c = make()
    p = tmp_path / "contacts.dat"
    p.write_text("broken", encoding="utf-8")
    c.contacts_path = p
    c.protect, c.unprotect = fake_protect, fake_unprotect
    assert c.address_book().contacts == []
    assert any("주소록을 읽지 못" in m for m in c.messages)


def test_MAPP_10_side_bar_has_mail(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    assert "mail" in c.overlays[0].side_bar.buttons


def test_MAPP_11_second_mail_replaces_the_old_helper(mail):
    c, _, _ = mail()
    c.on_toolbar_action("mail")
    first = c.mail_helper
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    c.on_toolbar_action("mail")
    assert c.mail_helper is not first and not first.isVisible()


def test_MAPP_12_picker_lists_book_groups_and_counts(qt_app):
    from capture_tool.app.mail_ui import MailPicker
    from capture_tool.core.settings import Settings
    b = C.AddressBook()
    b.add("팀장님", "boss@corp.com")
    b.add("이영희", "lee@corp.com")
    b.add_group("우리 팀", ["a@corp.com", "b@corp.com"])
    s = Settings()
    s.mail_provider = "gmail"
    d = MailPicker(b, s)
    d.set_tab("all")
    assert d.rows() == ["boss@corp.com", "lee@corp.com"]
    d.set_tab("groups")
    assert d.rows() == ["group:우리 팀"]
    d.check("group:우리 팀", field="cc")
    d.set_tab("all")
    d.check("boss@corp.com")
    d.search.setText("new@x.com")
    d.add_typed()
    choice = d.choice()
    assert choice.to == ["boss@corp.com", "new@x.com"] and choice.cc == ["group:우리 팀"]
    assert "4명" in d.go.text()
    d.search.setText("영희")
    d.set_tab("all")
    assert d.rows() == ["lee@corp.com"]


def test_MAPP_13_picker_refuses_a_bad_typed_address(qt_app):
    from capture_tool.app.mail_ui import MailPicker
    from capture_tool.core.settings import Settings
    d = MailPicker(C.AddressBook(), Settings())
    d.search.setText("not an address")
    d.add_typed()
    assert d.choice().to == [] and "올바른" in d.status.text()
    assert d.provider.currentData() in ("naver", "gmail", "naverworks", "daum", "outlook", "mailto", "custom")


def test_MAPP_14_mail_settings_are_saved(tmp_path):
    from capture_tool.core.settings import Settings, load, save
    s = Settings()
    s.mail_provider, s.mail_account, s.mail_custom_url = "gmail", "me@gmail.com", "https://m.corp.com/new?to={to}"
    save(s, tmp_path / "s.json")
    back, _ = load(tmp_path / "s.json")
    assert (back.mail_provider, back.mail_account, back.mail_custom_url) == ("gmail", "me@gmail.com",
                                                                              "https://m.corp.com/new?to={to}")


def test_MAPP_15_contacts_editor_keeps_good_rows_and_reports_bad_ones(qt_app):
    from capture_tool.app.mail_ui import ContactsDialog
    b = C.AddressBook()
    b.add("팀장님", "boss@corp.com")
    b.add("지울 사람", "gone@corp.com")
    d = ContactsDialog(b)
    d.table.removeRow(1)
    d._add_row("새 사람", "new@x.com")
    d._add_row("잘못", "not-an-email")
    problems = d.apply_rows()
    assert len(problems) == 1 and "3번째" in problems[0]
    assert [c.email for c in b.contacts] == ["boss@corp.com", "new@x.com"]


def test_MAPP_16_settings_dialog_mail_section(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    from capture_tool.core.settings import Settings
    d = SettingsDialog(Settings())
    d.mail_provider.setCurrentIndex(d.mail_provider.findData("custom"))
    d.mail_custom.setText("javascript:alert(1)")
    assert any("메일 쓰기 주소" in e for e in d.validate())
    d.mail_custom.setText("https://mail.corp.com/new?to={to}")
    d.mail_account.setText("me@gmail.com")
    assert not any("메일" in e for e in d.validate())
    s = d.result_settings()
    assert (s.mail_provider, s.mail_custom_url, s.mail_account) == ("custom", "https://mail.corp.com/new?to={to}",
                                                                     "me@gmail.com")


def test_MAPP_17_without_prefill_the_recipients_are_ready_to_paste_first(mail):
    """Naver etc. can't take recipients in the address: the compose page opens with the
    recipients already on the clipboard (one Ctrl+V in 받는 사람), step ① shown as done."""
    c, _, _ = mail()
    c.on_toolbar_action("mail")
    assert c.clipboard.last[UNICODE] == "boss@corp.com"
    assert "✓" in c.mail_helper.buttons["to"].text()


def test_MAPP_18_with_prefill_the_capture_is_ready_to_paste(mail):
    from capture_tool.app.mail_ui import MailChoice
    c, _, _ = mail(MailChoice(["boss@corp.com"], [], "gmail"), provider="gmail")
    c.on_toolbar_action("mail")
    assert PNG in c.clipboard.last


def test_MAPP_19_naver_opens_with_recipients_and_subject(mail):
    """Bug (v0.7.2): Naver's compose page opened with 받는 사람 empty. The person confirmed that
    /write/popup?to=…&subject=… fills both."""
    from urllib.parse import parse_qs, urlsplit
    from capture_tool.app.mail_ui import MailChoice
    c, opened, _ = mail(MailChoice(["boss@corp.com", "lee@corp.com"], [], "naver"), provider="naver")
    c.on_toolbar_action("mail")
    u = urlsplit(opened[0])
    assert (u.netloc, u.path) == ("mail.naver.com", "/write/popup")
    q = parse_qs(u.query)
    assert q["to"] == ["boss@corp.com,lee@corp.com"] and q["subject"][0].startswith("캡처 공유")
    assert PNG in c.clipboard.last and "이미 채워" in c.mail_helper.hint.text()
