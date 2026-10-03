"""Text that isn't laid out as a table, split into a table the person can preview and fix:
"항목: 값" pairs, 2+ spaces / tabs, commas, one cell per line, or their own separator."""
import pytest

from capture_tool.core.table_split import RULES, split_table

NOTICE = ["사내 공지", "• 일시: 10월 15일(수) 오후 2~6시", "• 대상: 메일, 결재, 인사 시스템",
          "• 담당: 정보보안팀 김민수 대리", "• 문의: 내선 2041"]


def test_SPL_01_pairs_with_title_and_bullets():
    title, rows = split_table(NOTICE, "pair")
    assert title == "사내 공지"
    assert rows == [["일시", "10월 15일(수) 오후 2~6시"], ["대상", "메일, 결재, 인사 시스템"],
                    ["담당", "정보보안팀 김민수 대리"], ["문의", "내선 2041"]]


def test_SPL_02_auto_picks_pairs_for_a_label_list():
    assert split_table(NOTICE, "auto") == split_table(NOTICE, "pair")


def test_SPL_03_options_keep_title_bullets_and_add_header():
    title, rows = split_table(NOTICE, "pair", title_first=False, strip_bullets=False, header=True)
    assert title is None
    assert rows[0] == ["항목", "내용"] and rows[1] == ["사내 공지", ""] and rows[2][0] == "• 일시"


def test_SPL_04_spaces_and_tabs():
    lines = ["품목\t수량\t금액", "사과   3   9,000", "배\t5\t15,000"]
    _, rows = split_table(lines, "spaces", title_first=False)
    assert rows == [["품목", "수량", "금액"], ["사과", "3", "9,000"], ["배", "5", "15,000"]]


def test_SPL_05_comma_keeps_number_commas_together():
    lines = ["이름, 부서, 금액", "김, 영업, 1,250,000", "이, 인사, 900"]
    _, rows = split_table(lines, "comma", title_first=False)
    assert rows == [["이름", "부서", "금액"], ["김", "영업", "1,250,000"], ["이", "인사", "900"]]


def test_SPL_06_one_cell_per_line_and_custom_separator():
    _, rows = split_table(["가", "나", "", "다"], "line", title_first=False)
    assert rows == [["가"], ["나"], ["다"]]
    _, rows = split_table(["a/b/c", "d/e"], "custom:/", title_first=False)
    assert rows == [["a", "b", "c"], ["d", "e", ""]]


@pytest.mark.parametrize("lines", [[], [""], ["   "]])
def test_SPL_07_empty_input(lines):
    assert split_table(lines, "auto") == (None, [])


def test_SPL_08_ragged_rows_are_padded_and_size_capped():
    from capture_tool.core.table_split import MAX_COLS, MAX_ROWS
    _, rows = split_table(["a,b,c", "d"], "comma", title_first=False)
    assert rows == [["a", "b", "c"], ["d", "", ""]]
    big = [",".join(str(i) for i in range(80))] * 900
    _, rows = split_table(big, "comma", title_first=False)
    assert len(rows) <= MAX_ROWS and len(rows[0]) <= MAX_COLS


def test_SPL_09_unknown_rule_falls_back_to_auto_and_empty_custom_is_line():
    assert split_table(NOTICE, "zzz") == split_table(NOTICE, "auto")
    _, rows = split_table(["a b"], "custom:", title_first=False)
    assert rows == [["a b"]]


def test_SPL_10_title_only_when_the_first_line_has_no_separator():
    lines = ["일시: 오늘", "장소: 2층", "담당: 김"]
    title, rows = split_table(lines, "pair")
    assert title is None and len(rows) == 3


def test_SPL_11_random_text_never_breaks():
    import random
    rnd = random.Random(5)
    alpha = "가나 ab:,\t/•-  12"
    for _ in range(2000):
        lines = ["".join(rnd.choice(alpha) for _ in range(rnd.randint(0, 40))) for _ in range(rnd.randint(0, 8))]
        for rule in RULES:
            title, rows = split_table(lines, rule)
            assert all(len(r) == len(rows[0]) for r in rows)
