"""Tables whose cells wrap onto several lines, rows separated by lines (Kakao/web/terminal
output): one table row per band between the separator lines, the wrapped lines rejoined in their
cell - without a space where the line was cut in the middle of a word."""
from pathlib import Path

import cv2
import pytest

from capture_tool.core.ocr import OcrEngine
from capture_tool.core.table_capture import find_table, join_wrapped

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def kakao():
    img = cv2.imread(str(DATA / "kakao_rules_table.png"))
    lines = [(l.text, l.box, l.score) for l in OcrEngine().recognize(img)]
    return find_table(img, lines, [], 96)


def flat(s):
    return s.replace(" ", "")


def test_WRAP_01_one_row_per_band(kakao):
    """User (v0.8.1): every wrapped line became its own row; cells had to be merged by hand."""
    assert kakao is not None
    assert len(kakao.rows) == 5 and all(len(r) == 4 for r in kakao.rows), kakao.rows
    assert [r[0] for r in kakao.rows][:3] == ["방식", "LOCO 직접 접속", "안드로이드 알림 봇"]


def test_WRAP_02_wrapped_text_rejoined_in_its_cell(kakao):
    rows = {flat(r[0]): r for r in kakao.rows}
    loco = rows["LOCO직접접속"]
    assert flat(loco[1]) == "프로그램이카톡클라이언트처럼서버에로그인해메시지를받고보냄", loco
    assert "클라이언트처럼" in loco[1] and "메시지를" in loco[1]              # cut mid-word: no space
    assert flat(loco[2]) == "같은계정의PC접속과충돌할수있음"
    bot = rows["안드로이드알림봇"]
    assert "만들지 않음" in bot[2], bot
    assert "읽고 알림의" in bot[1], bot                                        # cut at a space: kept
    db = [r for k, r in rows.items() if k.startswith("안드로이드") and k != "안드로이드알림봇"][0]
    assert flat(db[3]) == "루팅등설치조건이까다로움" and "까다로움" in db[3], db


def test_WRAP_03_join_rule():
    # (text, right edge) of each line; the column's text reaches x=300; letters ~16 px wide
    assert join_wrapped([("카톡 클라이언트", 299), ("처럼 서버에", 120)], 300, 16) == "카톡 클라이언트처럼 서버에"
    assert join_wrapped([("메시지를 읽고", 270), ("알림의 답장", 150)], 300, 16) == "메시지를 읽고 알림의 답장"
    assert join_wrapped([("메시지를 읽고", 299), ("알림의 답장", 150)], 300, 16) == "메시지를 읽고 알림의 답장"
    assert join_wrapped([("one", 50)], 300, 16) == "one"
    assert join_wrapped([("end.", 299), ("Next", 40)], 300, 16) == "end. Next"     # after punctuation: a space
    assert join_wrapped([], 300, 16) == ""
