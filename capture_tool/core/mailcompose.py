"""Mail compose pages opened in the person's own browser (their own sign-in; nothing is sent by
us). Only services with a known way to fill To/Cc/Subject get them in the address (Gmail,
Outlook web, mailto); every other service opens its compose page and the helper window gives
the person each piece to paste."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode

MAX_URL = 1800            # browsers and mail sites cut longer addresses; beyond it: helper only


@dataclass(frozen=True)
class Provider:
    label: str
    url: str                 # compose page (or home page when there is no compose address)
    prefill: str = ""        # "gmail" | "outlook" | "mailto" | "" (none)


PROVIDERS = {
    "gmail": Provider("Gmail", "https://mail.google.com/mail/?view=cm&fs=1", "gmail"),
    # confirmed by a signed-in user (2026-10-03): the popup compose page fills To and Subject
    "naver": Provider("네이버 메일", "https://mail.naver.com/write/popup", "naver"),
    "naverworks": Provider("네이버웍스", "https://mail.worksmobile.com/"),
    "daum": Provider("다음 메일", "https://mail.daum.net/"),
    "outlook": Provider("Outlook (웹)", "https://outlook.office.com/mail/deeplink/compose", "outlook"),
    "mailto": Provider("PC 기본 메일 앱", "mailto:", "mailto"),
    "custom": Provider("직접 입력", ""),
}

_DOMAINS = {"gmail.com": "gmail", "googlemail.com": "gmail", "naver.com": "naver", "hanmail.net": "daum",
            "daum.net": "daum", "outlook.com": "outlook", "hotmail.com": "outlook", "live.com": "outlook",
            "msn.com": "outlook"}


@dataclass
class Compose:
    url: str
    prefilled: bool          # To/Cc/Subject already in the compose page


def valid_custom(template: str) -> bool:
    """A company mail's compose address: https:// (or mailto:), braces only as {to} {cc} {subject}."""
    if not isinstance(template, str) or not re.match(r"^(https://[^\s/\\]+\S*|mailto:\S*)$", template):
        return False
    rest = re.sub(r"\{(to|cc|subject)\}", "", template)
    return "{" not in rest and "}" not in rest


def _q(v: str) -> str:
    return quote(v, safe="@")


def compose(provider: str, to: list[str], cc: list[str], subject: str, account: str = "",
            custom: str = "") -> Compose:
    p = PROVIDERS.get(provider)
    if p is None:
        raise ValueError(f"unknown mail service {provider!r}")
    to_s, cc_s = ",".join(to), ",".join(cc)
    if provider == "custom":
        if not valid_custom(custom):
            raise ValueError("메일 쓰기 주소는 https:// 로 시작해야 합니다.")
        filled = any(k in custom for k in ("{to}", "{cc}", "{subject}"))
        url = custom.replace("{to}", _q(to_s)).replace("{cc}", _q(cc_s)).replace("{subject}", _q(subject))
        base = re.sub(r"[?&][^?&]*\{(to|cc|subject)\}[^&]*", "", custom)
        return Compose(url, filled) if len(url) <= MAX_URL else Compose(base, False)
    if p.prefill == "gmail":
        q = {"to": to_s}
        if cc_s:
            q["cc"] = cc_s
        q["su"] = subject
        if account:
            q["authuser"] = account
        url = p.url + "&" + urlencode(q, quote_via=quote, safe="@,")
        base = p.url + (("&" + urlencode({"authuser": account}, quote_via=quote, safe="@")) if account else "")
    elif p.prefill == "naver":
        q = {"to": to_s}
        if cc_s:
            q["cc"] = cc_s
        q["subject"] = subject
        url = p.url + "?" + urlencode(q, quote_via=quote, safe="@,")
        base = p.url
    elif p.prefill == "outlook":
        q = {"to": to_s}
        if cc_s:
            q["cc"] = cc_s
        q["subject"] = subject
        url = p.url + "?" + urlencode(q, quote_via=quote, safe="@,")
        base = p.url
    elif p.prefill == "mailto":
        q = {}
        if cc_s:
            q["cc"] = cc_s
        q["subject"] = subject
        url = "mailto:" + quote(to_s, safe="@,") + "?" + urlencode(q, quote_via=quote, safe="@,")
        base = "mailto:"
    else:
        return Compose(p.url, False)
    if len(url) > MAX_URL:
        return Compose(base, False)
    return Compose(url, True)


def suggest(email: str) -> str | None:
    m = re.fullmatch(r"[^@\s]+@([^@\s]+)", (email or "").strip())
    return _DOMAINS.get(m.group(1).lower()) if m else None


def default_subject(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"캡처 공유 — {now.month}월 {now.day}일 {now:%H:%M}"


def recipients_text(emails: list[str]) -> str:
    return ", ".join(emails)
