"""AI answers (or any text) laid out like a table -> real table cells for Excel / PowerPoint."""
import pytest

from capture_tool.core.text_table import find_text_table


def test_TXT_01_markdown_pipe_table_with_intro_and_outro():
    text = ("분기별 실적은 다음과 같습니다.\n\n"
            "| 분기 | 매출 | **증감** |\n|:---|---:|:-:|\n| 3분기 | 1,250억 | 12% |\n| 4분기 | 1,320억 | 5.6% |\n\n"
            "참고: 단위는 원입니다.")
    t = find_text_table(text)
    assert t.rows == [["분기", "매출", "증감"], ["3분기", "1,250억", "12%"], ["4분기", "1,320억", "5.6%"]]
    assert t.kind == "grid"


def test_TXT_02_pipe_rows_without_outer_bars_and_ragged_rows_are_padded():
    t = find_text_table("이름 | 부서 | 내선\n김민수 | 정보보안팀 | 2041\n이영희 | 인사팀")
    assert t.rows == [["이름", "부서", "내선"], ["김민수", "정보보안팀", "2041"], ["이영희", "인사팀", ""]]


def test_TXT_03_tab_separated():
    t = find_text_table("품목\t수량\n사과\t3\n배\t5")
    assert t.rows == [["품목", "수량"], ["사과", "3"], ["배", "5"]] and t.kind == "grid"


def test_TXT_04_columns_aligned_with_spaces():
    text = ("항목        2025년      2026년\n"
            "매출        1,100억     1,250억\n"
            "영업이익    100억       96억")
    t = find_text_table(text)
    assert t.rows == [["항목", "2025년", "2026년"], ["매출", "1,100억", "1,250억"], ["영업이익", "100억", "96억"]]


def test_TXT_05_label_value_lines_become_two_columns_but_only_as_a_weak_table():
    text = "• 일시: 10월 15일(수) 오후 2~6시\n• 대상: 메일, 결재, 인사 시스템\n• 문의: 김민수 대리(내선 2041)"
    t = find_text_table(text)
    assert t.rows == [["일시", "10월 15일(수) 오후 2~6시"], ["대상", "메일, 결재, 인사 시스템"],
                      ["문의", "김민수 대리(내선 2041)"]]
    assert t.kind == "pairs"                 # PPT로 keeps it as text; 표로 복사 still works


@pytest.mark.parametrize("text", [
    "", "그냥 한 문장입니다.", "• 매출 증가\n• 이익 감소\n• 신제품 출시",
    "회의는 3시 | 장소는 2층",                          # one line is not a table
    "시간: 3시\n장소: 2층",                              # two label lines are not enough
    "|---|---|\n|---|---|",                              # separators only
    "URL: https://a.b/c?x=1|2\n일반 문장입니다.\n또 다른 문장.",
])
def test_TXT_06_ordinary_text_is_not_a_table(text):
    assert find_text_table(text) is None


def test_TXT_07_largest_table_block_wins_and_times_are_not_split():
    text = ("시간: 오후 2:30\n장소: 2층\n담당: 김\n\n"
            "| 이름 | 점수 |\n|---|---|\n| 가 | 1 |\n| 나 | 2 |\n| 다 | 3 |\n| 라 | 4 |")
    t = find_text_table(text)
    assert t.rows[0] == ["이름", "점수"] and len(t.rows) == 5
    t2 = find_text_table("시간: 오후 2:30\n장소: 2층\n담당: 김")
    assert t2.rows[0] == ["시간", "오후 2:30"]


def test_TXT_08_cells_are_cleaned_and_size_is_capped():
    from capture_tool.core.text_table import MAX_COLS, MAX_ROWS
    t = find_text_table("| `코드` | **이름** |\n|---|---|\n| <b>1</b> | 가\\|나 |")
    assert t.rows == [["코드", "이름"], ["1", "가|나"]]
    big = "\n".join("| " + " | ".join(str(c) for c in range(80)) + " |" for _ in range(900))
    t = find_text_table(big)
    assert len(t.rows) <= MAX_ROWS and len(t.rows[0]) <= MAX_COLS and t.cut


def test_TXT_09_random_text_never_breaks():
    import random
    rnd = random.Random(3)
    alphabet = "가나 ab|:\t-*`•\n  12,.%"
    for _ in range(3000):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 200)))
        t = find_text_table(s)
        if t is not None:
            assert len(t.rows) >= 2 and all(len(r) == len(t.rows[0]) for r in t.rows)
