"""Address book for 메일: per Windows user, encrypted on disk, groups / recent / frequent,
CSV import (Gmail, Naver, Excel cp949) and export, and the edge cases around them."""
import json

import pytest

from capture_tool.core import contacts as C
from capture_tool.core.contacts import AddressBook, InvalidEmail, normalize_email


# --- addresses -------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,want", [
    ("Kim@Example.COM", "Kim@example.com"), ("  a.b+tag@sub.example.co.kr ", "a.b+tag@sub.example.co.kr"),
    ("이영희 <lee@회사.com>", "lee@회사.com"), ("mailto:x@y.io", "x@y.io"),
])
def test_CON_01_addresses_are_normalized(raw, want):
    assert normalize_email(raw) == want


@pytest.mark.parametrize("bad", ["", "abc", "a@", "@b.com", "a@b", "a b@c.com", "a@b..com", "a@@b.com",
                                 "a@b.com, c@d.com", "x" * 250 + "@a.com", "a@-b.com", "a@b.com\n"])
def test_CON_02_bad_addresses_are_refused(bad):
    with pytest.raises(InvalidEmail):
        normalize_email(bad)


# --- book ----------------------------------------------------------------------------------------
def book():
    b = AddressBook()
    b.add("팀장님", "manager@corp.com")
    b.add("이영희", "lee@corp.com")
    b.add("박 과장", "park@partner.co.kr")
    b.add_group("우리 팀", ["lee@corp.com", "kim@corp.com", "choi@corp.com"])
    return b


def test_CON_03_same_address_twice_updates_the_name_not_a_second_entry():
    b = book()
    b.add("팀장", "MANAGER@corp.com")
    assert [c.email for c in b.contacts].count("manager@corp.com") == 1
    assert b.get("manager@corp.com").name == "팀장"


def test_CON_04_empty_name_uses_the_address():
    b = AddressBook()
    assert b.add("", "solo@x.com").name == "solo@x.com"


def test_CON_05_search_by_name_or_address_ignoring_case():
    b = book()
    assert [c.email for c in b.search("영희")] == ["lee@corp.com"]
    assert [c.email for c in b.search("PARTNER")] == ["park@partner.co.kr"]
    assert len(b.search("")) == 3


def test_CON_06_removing_a_contact_also_leaves_its_groups():
    b = book()
    b.remove("lee@corp.com")
    assert b.get("lee@corp.com") is None
    assert "lee@corp.com" not in b.group("우리 팀").members


def test_CON_07_groups_expand_and_duplicates_collapse_to_the_strongest_field():
    b = book()
    to, cc = b.resolve(["manager@corp.com", "lee@corp.com"], ["group:우리 팀", "manager@corp.com"])
    assert to == ["manager@corp.com", "lee@corp.com"]
    assert cc == ["kim@corp.com", "choi@corp.com"]          # lee is already in To, manager too


def test_CON_08_unknown_group_and_bad_entries_are_skipped():
    b = book()
    to, cc = b.resolve(["group:없는 그룹", "not-an-email", "new@x.com"], [])
    assert to == ["new@x.com"] and cc == []


def test_CON_09_frequent_and_recent_follow_use():
    b = book()
    b.mark_used(["park@partner.co.kr"])
    b.mark_used(["park@partner.co.kr", "lee@corp.com"])
    assert [c.email for c in b.frequent(2)] == ["park@partner.co.kr", "lee@corp.com"]
    assert b.recent[:2] == ["park@partner.co.kr", "lee@corp.com"] or b.recent[:2] == ["lee@corp.com", "park@partner.co.kr"]
    b.mark_used([f"r{i}@x.com" for i in range(40)])
    assert len(b.recent) == C.MAX_RECENT


def test_CON_10_size_is_capped():
    b = AddressBook()
    for i in range(C.MAX_CONTACTS + 10):
        try:
            b.add("", f"u{i}@x.com")
        except C.BookFull:
            break
    assert len(b.contacts) == C.MAX_CONTACTS


# --- storage ---------------------------------------------------------------------------------------
def fake_protect(s):
    return "ENC:" + s[::-1]


def fake_unprotect(s):
    if not s.startswith("ENC:"):
        raise C.SecretError("no")
    return s[4:][::-1]


def test_CON_11_saved_file_does_not_show_addresses_and_loads_back(tmp_path):
    p = tmp_path / "contacts.dat"
    b = book()
    b.mark_used(["park@partner.co.kr"])
    C.save(b, p, protect=fake_protect)
    raw = p.read_text(encoding="utf-8")
    assert "manager@corp.com" not in raw and "팀장님" not in raw
    back, warn = C.load(p, unprotect=fake_unprotect)
    assert warn == "" and [c.email for c in back.contacts] == [c.email for c in b.contacts]
    assert back.group("우리 팀").members == b.group("우리 팀").members and back.recent == b.recent


def test_CON_12_missing_file_is_an_empty_book(tmp_path):
    back, warn = C.load(tmp_path / "none.dat", unprotect=fake_unprotect)
    assert back.contacts == [] and warn == ""


def test_CON_13_unreadable_file_is_kept_aside_not_deleted(tmp_path):
    """Another Windows user's file, a reinstall that lost the key, a broken file: start empty,
    keep the old file next to it so nothing is lost, and say so."""
    p = tmp_path / "contacts.dat"
    p.write_text("garbage", encoding="utf-8")
    back, warn = C.load(p, unprotect=fake_unprotect)
    assert back.contacts == [] and "읽지 못" in warn
    kept = list(tmp_path.glob("contacts.unreadable-*.dat"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "garbage"


def test_CON_14_save_is_atomic(tmp_path, monkeypatch):
    p = tmp_path / "contacts.dat"
    C.save(book(), p, protect=fake_protect)
    before = p.read_text(encoding="utf-8")

    def boom(s):
        raise C.SecretError("fail")
    with pytest.raises(C.SecretError):
        C.save(AddressBook(), p, protect=boom)
    assert p.read_text(encoding="utf-8") == before            # the old book survives a failed save


# --- CSV -----------------------------------------------------------------------------------------------
GMAIL = ("Name,Given Name,Family Name,E-mail 1 - Type,E-mail 1 - Value,E-mail 2 - Value\n"
         "팀장님,,,* Work,manager@corp.com,boss@home.com\n"
         ",,,* Home,nobody@x.com,\n"
         "잘못,,,*,not-email,\n")
NAVER = "이름,이메일,휴대폰\n이영희,lee@corp.com,010-0000-0000\n박 과장,park@partner.co.kr,\n"


def test_CON_15_gmail_csv():
    found, skipped = C.import_csv(GMAIL.encode("utf-8-sig"))
    assert [(c.name, c.email) for c in found] == [("팀장님", "manager@corp.com"), ("팀장님", "boss@home.com"),
                                                   ("nobody@x.com", "nobody@x.com")]
    assert len(skipped) == 1


def test_CON_16_naver_csv_saved_by_excel_in_cp949():
    found, skipped = C.import_csv(NAVER.encode("cp949"))
    assert [(c.name, c.email) for c in found] == [("이영희", "lee@corp.com"), ("박 과장", "park@partner.co.kr")]
    assert skipped == []


def test_CON_17_unknown_columns_still_find_addresses():
    data = "회사,담당자,연락처\nA사,홍길동,hong@a.com\nB사,,b@b.com\n".encode("utf-8")
    found, _ = C.import_csv(data)
    assert [c.email for c in found] == ["hong@a.com", "b@b.com"] and found[0].name == "홍길동"


@pytest.mark.parametrize("data", [b"", b"\x00\x01\x02garbage", "이름\n".encode("utf-8"), b"a,b\n" * 3])
def test_CON_18_csv_without_addresses_is_empty_not_an_error(data):
    found, _ = C.import_csv(data)
    assert found == []


def test_CON_19_export_csv_round_trips_and_defuses_formulas():
    b = AddressBook()
    b.add("=HYPERLINK(\"http://evil\")", "x@y.com")
    b.add("홍길동", "hong@a.com")
    data = C.export_csv(b)
    text = data.decode("utf-8-sig")
    assert "'=HYPERLINK" in text                                  # Excel won't run it
    found, _ = C.import_csv(data)
    assert {c.email for c in found} == {"x@y.com", "hong@a.com"}


def test_CON_20_huge_csv_is_bounded():
    rows = "".join(f"u{i},u{i}@x.com\n" for i in range(C.MAX_CONTACTS * 2))
    found, _ = C.import_csv(("name,email\n" + rows).encode("utf-8"))
    assert len(found) == C.MAX_CONTACTS


def test_CON_21_book_json_ignores_junk_fields():
    data = {"contacts": [{"name": "a", "email": "a@x.com"}, {"name": 3, "email": "bad"}, "junk"],
            "groups": [{"name": "g", "members": ["a@x.com", "bad"]}, {"bad": 1}], "recent": ["a@x.com", 5], "uses": {"a@x.com": "x"}}
    b = AddressBook.from_json(json.dumps(data))
    assert [c.email for c in b.contacts] == ["a@x.com"] and b.group("g").members == ["a@x.com"]
    assert b.recent == ["a@x.com"]
