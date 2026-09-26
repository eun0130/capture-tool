import pytest

from capture_tool.core.redact import find_pii, mask_word_boxes


def kinds(text):
    return [(text[m.start:m.end], m.kind) for m in find_pii(text)]


def test_PII_01_email():
    assert kinds("담당 gil.dong+q@mail.example.co.kr 입니다") == [("gil.dong+q@mail.example.co.kr", "email")]
    assert kinds("a@b 는 아님") == []


@pytest.mark.parametrize("num", ["010-1234-5678", "010 1234 5678", "01012345678", "+82 10-1234-5678", "011-123-4567"])
def test_PII_02_mobile(num):
    assert kinds(f"연락처: {num}.") == [(num, "phone")]


@pytest.mark.parametrize("num", ["02-123-4567", "031-1234-5678", "(02)1234-5678"])
def test_PII_03_landline(num):
    found = kinds(f"tel {num}")
    assert len(found) == 1 and found[0][1] == "phone"
    assert found[0][0] in num


def test_PII_04_rrn():
    assert kinds("주민 900101-1234567 끝") == [("900101-1234567", "rrn")]


def test_PII_05_card_luhn_valid():
    assert kinds("카드 4111-1111-1111-1111") == [("4111-1111-1111-1111", "card")]
    assert kinds("카드 4111111111111111") == [("4111111111111111", "card")]


def test_PII_06_card_luhn_invalid():
    assert kinds("번호 4111-1111-1111-1112") == []


@pytest.mark.parametrize("text", ["2026-09-26 회의", "버전 1.2.3", "금액 1,234,567원", "010-12", "주문번호 20260926-0001"])
def test_PII_07_not_pii(text):
    assert kinds(text) == []


def test_PII_08_split_words_all_masked():
    words = [("연락처:", (0, 0, 50, 10)), ("010", (60, 0, 20, 10)), ("1234", (85, 0, 30, 10)),
             ("5678", (120, 0, 30, 10)), ("감사", (160, 0, 30, 10))]
    assert mask_word_boxes(words) == [(60, 0, 20, 10), (85, 0, 30, 10), (120, 0, 30, 10)]


def test_PII_09_empty():
    assert find_pii("") == []
    assert mask_word_boxes([]) == []


def test_multiple_sorted_non_overlapping():
    t = "a@b.com 010-1111-2222 x@y.org"
    ks = [k for _, k in kinds(t)]
    assert ks == ["email", "phone", "email"]
