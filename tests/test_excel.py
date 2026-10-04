"""표 → 엑셀: when Excel is open the table goes to its selected cell (like Word / PowerPoint);
when it isn't, the table waits on the clipboard with a clear 'Ctrl+V' message. Excel is never
started just for this."""
from capture_tool.core.clipboard_payload import HTML
from capture_tool.platform.excel import ExcelNotOpen, paste_into_open_excel
from tests.test_app import make  # noqa: F401 (fixture)


class FakeCell:
    def Address(self, a, b):
        return "B3"


class FakeSheet:
    Name = "Sheet1"

    def __init__(self, calls):
        self.calls = calls

    def Paste(self):
        self.calls.append("paste")


class FakeExcelApp:
    def __init__(self, workbook=True):
        self.calls = []
        self.ActiveWorkbook = object() if workbook else None
        self.ActiveSheet = FakeSheet(self.calls)
        self.ActiveCell = FakeCell()
        self.Visible = False
        self.ActiveWindow = type("W", (), {"Activate": lambda s: None})()


def test_EXCEL_01_paste_at_the_selected_cell():
    app = FakeExcelApp()
    assert paste_into_open_excel(app_factory=lambda: app) == "Sheet1!B3" and app.calls == ["paste"]


def test_EXCEL_02_no_workbook_means_not_open():
    import pytest
    with pytest.raises(ExcelNotOpen):
        paste_into_open_excel(app_factory=lambda: FakeExcelApp(workbook=False))


def test_EXCEL_03_table_goes_into_open_excel(make):
    """User (v0.8.5): with Excel open, 표 → 엑셀 showed nothing in Excel."""
    c = make()
    c.excel = type("E", (), {"paste": lambda self: "Sheet1!B3", "busy": False})()
    c.settings.table_style = "plain"
    c._deliver_table([["항목", "값"], ["a", "1"]], None, None, [], target="excel")
    assert HTML in c.clipboard.last and "B3" in c.messages[-1]


def test_EXCEL_04_without_excel_the_table_waits_on_the_clipboard(make):
    c = make()                                    # the test guard: not open, not installed
    c._deliver_table([["항목", "값"], ["a", "1"]], None, None, [], target="excel")
    assert HTML in c.clipboard.last and "Ctrl+V" in c.messages[-1] and "설치" in c.messages[-1]


def test_EXCEL_05_messages_stay_long_enough_to_read():
    from capture_tool.app.toast import SHOW_MS, toast_ms
    assert toast_ms("짧음") == SHOW_MS
    long = "표 5행×3열(흰 바탕·검은 글씨)로 복사했습니다. 엑셀에서 붙일 칸을 누르고 Ctrl+V 하세요."
    assert toast_ms(long) >= 5000 and toast_ms("가" * 500) <= 10000


def test_EXCEL_06_closed_excel_is_started_and_gets_the_table():
    """User (v0.8.6): with Excel closed, 표 → 엑셀 should open Excel and paste right away."""
    from capture_tool.platform import excel
    app = FakeExcelApp(workbook=False)
    started = []

    def start():
        started.append(True)
        app.ActiveWorkbook = object()                   # a new workbook, A1 selected
        return app

    def not_running():
        raise excel.ExcelNotOpen("x")
    where = excel.paste_into_excel(running=not_running, start=start, installed=lambda: True)
    assert started and app.calls == ["paste"] and where == "Sheet1!B3"


def test_EXCEL_07_no_excel_installed_stays_on_the_clipboard(make):
    from capture_tool.platform import excel

    def not_running():
        raise excel.ExcelNotOpen("x")
    import pytest
    with pytest.raises(excel.ExcelMissing):
        excel.paste_into_excel(running=not_running, start=lambda: None, installed=lambda: False)
    c = make()
    c.excel = type("E", (), {"paste": lambda self: (_ for _ in ()).throw(excel.ExcelMissing("없음")),
                             "busy": False})()
    c._deliver_table([["a", "b"], ["c", "d"]], None, None, [], target="excel")
    assert "Ctrl+V" in c.messages[-1] and "설치" in c.messages[-1]
