"""Opening a mail compose page in the person's own (already signed-in) browser: Gmail gets
To/Cc/Subject in the address; other services open their compose page and the helper window does
the rest; the address must never be something other than http(s)/mailto."""
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from capture_tool.core import mailcompose as M


def test_MAIL_01_gmail_is_prefilled_with_utf8_subject_and_account():
    c = M.compose("gmail", ["a@x.com", "b@y.com"], ["c@z.com"], "캡처 공유 — 10월 3일", account="me@gmail.com")
    u = urlsplit(c.url)
    q = parse_qs(u.query)
    assert u.scheme == "https" and u.netloc == "mail.google.com" and c.prefilled
    assert q["view"] == ["cm"] and q["to"] == ["a@x.com,b@y.com"] and q["cc"] == ["c@z.com"]
    assert q["su"] == ["캡처 공유 — 10월 3일"] and q["authuser"] == ["me@gmail.com"]


def test_MAIL_02_other_web_mail_opens_compose_without_guessing_parameters():
    for pid in ("naverworks", "daum"):
        c = M.compose(pid, ["a@x.com"], [], "제목")
        assert c.url.startswith("https://") and not c.prefilled
        assert "a@x.com" not in c.url and "제목" not in unquote(c.url)


def test_MAIL_03_outlook_web_and_mailto_prefill():
    o = M.compose("outlook", ["a@x.com"], ["c@z.com"], "제목")
    assert o.prefilled and o.url.startswith("https://outlook.office.com/mail/deeplink/compose?")
    assert parse_qs(urlsplit(o.url).query)["to"] == ["a@x.com"]
    m = M.compose("mailto", ["a@x.com", "b@y.com"], ["c@z.com"], "제 목&x")
    assert m.url.startswith("mailto:a@x.com,b@y.com?") and m.prefilled
    q = parse_qs(urlsplit(m.url).query)
    assert q["cc"] == ["c@z.com"] and q["subject"] == ["제 목&x"]


def test_MAIL_04_too_many_recipients_skip_prefill_instead_of_a_broken_address():
    many = [f"person{i:03d}@example-company.co.kr" for i in range(120)]
    c = M.compose("gmail", many, [], "제목")
    assert not c.prefilled and len(c.url) < M.MAX_URL and "person000" not in c.url


def test_MAIL_05_custom_compose_address_template():
    c = M.compose("custom", ["a@x.com"], ["c@z.com"], "제목", custom="https://mail.corp.com/new?to={to}&cc={cc}&s={subject}")
    q = parse_qs(urlsplit(c.url).query)
    assert c.prefilled and q["to"] == ["a@x.com"] and q["s"] == ["제목"]
    plain = M.compose("custom", ["a@x.com"], [], "제목", custom="https://mail.corp.com/write")
    assert plain.url == "https://mail.corp.com/write" and not plain.prefilled


@pytest.mark.parametrize("bad", ["", "javascript:alert(1)", "file:///C:/x", "http://", "ftp://x", "C:\\Windows\\a.exe",
                                 "https://x.com/{to", "\\\\server\\share"])
def test_MAIL_06_custom_address_must_be_web_or_mailto(bad):
    assert not M.valid_custom(bad)
    with pytest.raises(ValueError):
        M.compose("custom", ["a@x.com"], [], "s", custom=bad)


def test_MAIL_07_injection_through_fields_is_encoded():
    c = M.compose("gmail", ["a@x.com&su=hijack"], [], "x&to=evil@e.com#frag")
    q = parse_qs(urlsplit(c.url).query)
    assert q["su"] == ["x&to=evil@e.com#frag"] and q["to"] == ["a@x.com&su=hijack"]
    assert urlsplit(c.url).fragment == ""


def test_MAIL_08_unknown_provider_is_an_error():
    with pytest.raises(ValueError):
        M.compose("nope", [], [], "")


def test_MAIL_09_suggest_service_from_own_address():
    assert M.suggest("me@gmail.com") == "gmail" and M.suggest("ME@Naver.com") == "naver"
    assert M.suggest("a@hanmail.net") == "daum" and M.suggest("a@daum.net") == "daum"
    assert M.suggest("a@outlook.com") == "outlook" and M.suggest("a@hotmail.com") == "outlook"
    assert M.suggest("a@corp.co.kr") is None and M.suggest("") is None and M.suggest("bad") is None


def test_MAIL_10_default_subject_and_recipient_text():
    assert M.default_subject(datetime(2026, 10, 3, 14, 5)) == "캡처 공유 — 10월 3일 14:05"
    assert M.recipients_text(["a@x.com", "b@y.com"]) == "a@x.com, b@y.com"
    assert M.recipients_text([]) == ""


def test_MAIL_11_every_preset_is_https_or_mailto():
    for pid, p in M.PROVIDERS.items():
        if pid in ("custom",):
            continue
        c = M.compose(pid, ["a@x.com"], [], "s")
        assert c.url.startswith(("https://", "mailto:")), pid
        assert p.label


def test_MAIL_12_naver_compose_popup_takes_to_cc_and_subject():
    c = M.compose("naver", ["a@x.com", "b@y.com"], ["c@z.com"], "캡처 공유 — 10월 3일")
    u = urlsplit(c.url)
    q = parse_qs(u.query)
    assert c.prefilled and u.netloc == "mail.naver.com" and u.path == "/write/popup"
    assert q["to"] == ["a@x.com,b@y.com"] and q["cc"] == ["c@z.com"] and q["subject"] == ["캡처 공유 — 10월 3일"]
    many = M.compose("naver", [f"person{i:03d}@example-company.co.kr" for i in range(120)], [], "s")
    assert not many.prefilled and "person000" not in many.url
