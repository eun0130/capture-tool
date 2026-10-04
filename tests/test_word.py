"""표 → Word: the same choices as Excel / PowerPoint (where, and the capture's look or plain); the
table is put on the clipboard and pasted into Word at the cursor (a new document if none)."""
import pytest

from capture_tool.core.clipboard_payload import HTML
from capture_tool.core.settings import Settings
from capture_tool.platform.word import WordUnavailable, insert_clipboard
from tests.test_app import make  # noqa: F401 (fixture)


class FakeSelection:
    def __init__(self, calls):
        self.calls = calls

    def Paste(self):
        self.calls.append("paste")


class FakeDocs:
    def __init__(self, app, n):
        self.app, self.Count = app, n

    def Add(self):
        self.app.calls.append("add")
        self.Count += 1
        return object()


class FakeWordApp:
    def __init__(self, docs=1):
        self.calls = []
        self.Visible = False
        self.Documents = FakeDocs(self, docs)
        self.Selection = FakeSelection(self.calls)
        self.ActiveDocument = object()

    def Activate(self):
        self.calls.append("activate")


class FakeWord:
    def __init__(self, ok=True):
        self.ok, self.calls, self.busy = ok, 0, False

    def insert(self, col_widths=None):
        self.calls += 1
        if not self.ok:
            raise WordUnavailable("Word가 설치되어 있지 않습니다.")
        return 1


def test_WORD_01_settings_and_menu_accept_word(make):
    from capture_tool.core import settings as S
    s, warn = Settings(), []
    S._apply(s, {"table_target": "word"}, warn)
    assert s.table_target == "word" and not warn
    c = make()
    c.on_toolbar_action("tableopt:target:word")
    assert c.settings.table_target == "word"
    from capture_tool.app.table_options import TARGETS
    assert "word" in [k for k, _, _ in TARGETS]


def test_WORD_02_side_bar_menu_has_word(qt_app):
    from PySide6.QtWidgets import QMenu
    from capture_tool.app.side_bar import SideBar
    m = QMenu()
    SideBar()._fill_table_menu(m, Settings())
    assert any("워드" in a.text() for a in m.actions())


def test_WORD_03_table_goes_into_word(make):
    c = make()
    c.word = FakeWord()
    c.settings.table_style = "keep"
    c._deliver_table([["품목", "수량"], ["노트북", "12"]], None, None, [], target="word")
    assert c.word.calls == 1 and HTML in c.clipboard.last
    assert "Word" in c.messages[-1] and "2행×2열" in c.messages[-1]


def test_WORD_04_word_missing_still_on_clipboard(make):
    c = make()
    c.word = FakeWord(ok=False)
    c._deliver_table([["a", "b"], ["c", "d"]], None, None, [], target="word")
    assert HTML in c.clipboard.last and "Ctrl+V" in c.messages[-1]


def test_WORD_05_paste_into_open_document_or_a_new_one():
    app = FakeWordApp(docs=1)
    insert_clipboard(app_factory=lambda: app)
    assert app.calls == ["paste", "activate"] and app.Visible
    app2 = FakeWordApp(docs=0)
    insert_clipboard(app_factory=lambda: app2)
    assert app2.calls[:2] == ["add", "paste"]


def test_WORD_06_preview_can_send_to_word(make):
    c = make()
    c.word = FakeWord()
    c.ask_table_preview = lambda rows, title: ("word", None, [["a", "b"], ["c", "d"]])
    from capture_tool.core.ocr import OcrLine
    c._table_preview([OcrLine("a b", (0, 0, 50, 10), 0.9), OcrLine("c d", (0, 20, 50, 10), 0.9)])
    assert c.word.calls == 1


def test_WORD_07_unknown_target_rejected():
    from capture_tool.core import settings as S
    s, warn = Settings(), []
    S._apply(s, {"table_target": "hwp"}, warn)
    assert s.table_target == "excel" and warn


def test_WORD_08_column_widths_fit_the_page():
    from capture_tool.platform.word import MIN_COL_PT, fit_widths
    out = fit_widths([54, 252, 747], 451)
    assert abs(sum(out) - 451) < 1 and min(out) >= MIN_COL_PT and out[2] > out[1] > out[0]
    assert fit_widths([100, 100], 451) == [100, 100]                   # already fits
    assert fit_widths([], 451) == []
