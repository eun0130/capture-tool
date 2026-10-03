"""표 on a capture that isn't laid out as a table: a preview shows how it will be split, the
person picks the rule, fixes cells, then copies it as a table or sends it to PowerPoint."""
import numpy as np

from capture_tool.core.ocr import OcrLine
from capture_tool.core.table_split import ocr_row_lines
from tests.test_app import FakeOcr, FakePpt, make  # noqa: F401 (fixture)

NOTICE = [OcrLine("사내 공지", (10, 10, 90, 20), 0.99),
          OcrLine("• 일시: 10월 15일(수) 오후 2~6시", (10, 40, 260, 20), 0.99),
          OcrLine("• 대상: 메일, 결재, 인사 시스템", (10, 70, 250, 20), 0.99),
          OcrLine("• 문의: 내선 2041", (10, 100, 150, 20), 0.99)]


def test_PRV_01_ocr_rows_keep_wide_gaps_as_tabs():
    items = [("품목", (10, 10, 40, 20)), ("수량", (200, 10, 40, 20)), ("사과", (10, 40, 40, 20)),
             ("박스", (55, 40, 40, 20)), ("3", (200, 40, 10, 20))]
    assert ocr_row_lines(items) == ["품목\t수량", "사과 박스\t3"]
    assert ocr_row_lines([]) == []


def test_PRV_02_dialog_previews_and_follows_the_rule(qt_app):
    from capture_tool.app.table_preview import TablePreview
    d = TablePreview([l.text for l in NOTICE])
    assert d.title_label.text().endswith("사내 공지") and d.table.rowCount() == 3 and d.table.columnCount() == 2
    d.set_rule("line")
    assert d.table.columnCount() == 1 and d.table.rowCount() == 4
    d.set_rule("pair")
    d.header.setChecked(True)
    assert d.table.item(0, 0).text() == "항목" and d.table.rowCount() == 4
    assert "4행 × 2열" in d.size_label.text()


def test_PRV_03_cells_can_be_fixed_and_rows_added_or_removed(qt_app):
    from capture_tool.app.table_preview import TablePreview
    d = TablePreview([l.text for l in NOTICE])
    d.table.item(0, 1).setText("10월 16일")
    d.add_row()
    d.table.setItem(3, 0, __import__("PySide6.QtWidgets", fromlist=["QTableWidgetItem"]).QTableWidgetItem("비고"))
    d.add_col()
    assert d.table.columnCount() == 3
    d.del_col()
    title, rows = d.result_rows()
    assert rows[0] == ["일시", "10월 16일"] and rows[3][0] == "비고" and title == "사내 공지"
    d.table.setCurrentCell(3, 0)
    d.del_row()
    assert len(d.result_rows()[1]) == 3


def test_PRV_04_custom_separator(qt_app):
    from capture_tool.app.table_preview import TablePreview
    d = TablePreview(["a/b/c", "d/e/f"])
    d.custom.setText("/")
    d.set_rule("custom")
    assert d.table.columnCount() == 3 and d.table.item(1, 2).text() == "f"


def _flow(make, answer):
    c = make(ocr=FakeOcr(NOTICE))
    c.powerpoint = FakePpt()
    seen = []

    def ask(lines, parent=None):
        seen.append(lines)
        return answer
    c.ask_table_preview = ask
    c._run_recognition_on(np.full((200, 400, 3), 255, np.uint8), "table", dpi=96)
    return c, seen


def test_PRV_05_copy_from_the_preview(make):
    from capture_tool.core.clipboard_payload import HTML, UNICODE
    c, seen = _flow(make, ("copy", "사내 공지", [["일시", "오늘"], ["대상", "메일"]]))
    assert seen and seen[0][0] == "사내 공지"
    assert c.clipboard.last[UNICODE] == "사내 공지\r\n일시\t오늘\r\n대상\t메일"
    assert "<table" in c.clipboard.last[HTML].decode("utf-8")
    assert any("표 2행×2열" in m for m in c.messages)


def test_PRV_06_send_to_powerpoint_from_the_preview(make):
    from capture_tool.platform.powerpoint import TableItem
    c, _ = _flow(make, ("ppt", None, [["a", "b"], ["c", "d"]]))
    item = c.powerpoint.items[-1]
    assert isinstance(item, TableItem) and item.rows == [["a", "b"], ["c", "d"]] and item.title is None


def test_PRV_07_empty_result_is_not_copied(make):
    c, _ = _flow(make, ("copy", None, []))
    assert any("비어" in m for m in c.messages)
