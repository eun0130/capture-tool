"""표 button options: where (Excel / PowerPoint) and how (the capture's look / white background
with black text). Asked the first time (with "다음부터 바로"), changeable from the ▾ menu."""
from pathlib import Path

import cv2

from capture_tool.core.clipboard_payload import HTML, UNICODE
from capture_tool.core.ocr import OcrLine
from tests.test_app import FakeOcr, FakePpt, make  # noqa: F401 (fixture)
from tests.test_table_capture import DARK_LINES, DPI

DATA = Path(__file__).parent / "data"


def run(make, quick=None, answer=None, target=None, style=None, kind="table"):
    img = cv2.imread(str(DATA / "dark_table.png"))
    c = make(ocr=FakeOcr([OcrLine(t, b, s) for t, b, s in DARK_LINES]))
    c.powerpoint = FakePpt()
    if quick is not None:
        c.settings.table_quick = quick
    if target:
        c.settings.table_target = target
    if style:
        c.settings.table_style = style
    asked = []
    c.ask_table_options = lambda settings, parent=None: (asked.append(1), answer)[1]
    c._run_recognition_on(img, kind, dpi=DPI)
    return c, asked


def test_TOPT_01_defaults():
    from capture_tool.core.settings import Settings
    s = Settings()
    assert (s.table_target, s.table_style, s.table_quick) == ("excel", "keep", False)


def test_TOPT_02_first_press_asks_and_remembers(make):
    from capture_tool.platform.powerpoint import TableItem
    c, asked = run(make, answer=("ppt", "plain", True))
    assert asked == [1]
    item = c.powerpoint.items[-1]
    assert isinstance(item, TableItem) and item.style is not None
    assert item.style.body_fill == "#FFFFFF" and item.style.body_text == "#000000"
    assert (c.settings.table_target, c.settings.table_style, c.settings.table_quick) == ("ppt", "plain", True)


def test_TOPT_03_quick_uses_the_saved_choice_without_asking(make):
    c, asked = run(make, quick=True, target="excel", style="plain")
    assert asked == []
    html = c.clipboard.last[HTML].decode("utf-8")
    assert "background:#FFFFFF" in html and "color:#000000" in html and "#1F1F1E" not in html
    assert "border:1px solid #000000" in html
    assert c.clipboard.last[UNICODE].split("\r\n")[1].startswith("축\t값")


def test_TOPT_04_keep_look_for_excel(make):
    c, _ = run(make, quick=True, target="excel", style="keep")
    html = c.clipboard.last[HTML].decode("utf-8")
    assert "#1F1F1E" in html or "#1F1F1F" in html or "background:#2" in html


def test_TOPT_05_cancelled_choice_copies_nothing(make):
    c, asked = run(make, answer=None)
    assert asked == [1] and not any(HTML in p for p in c.clipboard.payloads)
    assert any("취소" in m for m in c.messages)


def test_TOPT_06_menu_changes_the_settings(make):
    c = make()
    c.on_toolbar_action("tableopt:target:ppt")
    c.on_toolbar_action("tableopt:style:plain")
    c.on_toolbar_action("tableopt:quick:0")
    assert (c.settings.table_target, c.settings.table_style, c.settings.table_quick) == ("ppt", "plain", False)
    c.on_toolbar_action("tableopt:target:bogus")
    assert c.settings.table_target == "ppt"


def test_TOPT_07_side_bar_menu(qt_app):
    from capture_tool.app.side_bar import SideBar
    from capture_tool.core.settings import Settings
    bar = SideBar()
    seen = []
    bar.action.connect(seen.append)
    s = Settings()
    s.table_target, s.table_style = "excel", "keep"
    menu = bar.table_menu(s)
    acts = {a.text(): a for a in menu.actions() if not a.isSeparator()}
    assert acts["엑셀에 넣기"].isChecked() and acts["캡처 모양 그대로"].isChecked()
    acts["PPT에 넣기"].trigger()
    acts["흰 바탕 · 검은 글씨"].trigger()
    acts["미리 보고 고치기…"].trigger()
    assert seen == ["tableopt:target:ppt", "tableopt:style:plain", "table_preview"]


def test_TOPT_08_options_dialog(qt_app):
    from capture_tool.app.table_options import TableOptions
    from capture_tool.core.settings import Settings
    d = TableOptions(Settings())
    assert d.result() == ("excel", "keep", True)
    d.buttons["ppt"].click()
    d.buttons["plain"].click()
    d.quick.setChecked(False)
    assert d.result() == ("ppt", "plain", False)
    assert "PPT에 넣기" in d.go.text()


def test_TOPT_09_preview_on_demand_even_for_a_real_table(make):
    seen = []
    img = cv2.imread(str(DATA / "dark_table.png"))
    c = make(ocr=FakeOcr([OcrLine(t, b, s) for t, b, s in DARK_LINES]))
    c.ask_table_preview = lambda lines, parent=None: (seen.append(lines), None)[1]
    c._run_recognition_on(img, "table_preview", dpi=DPI)
    assert seen and "축\t값\t요구" in seen[0][1].replace("  ", "\t")


def test_TOPT_10_settings_saved(tmp_path):
    from capture_tool.core.settings import Settings, load, save
    s = Settings()
    s.table_target, s.table_style, s.table_quick = "ppt", "plain", True
    save(s, tmp_path / "s.json")
    back, _ = load(tmp_path / "s.json")
    assert (back.table_target, back.table_style, back.table_quick) == ("ppt", "plain", True)


def test_TOPT_11_table_button_arrow_does_not_cover_its_label(qt_app):
    """Bug (v0.7.3): the ▾ of the 표 button was drawn over the word "표"."""
    from capture_tool.app.side_bar import SideBar
    bar = SideBar()
    b = bar.buttons["table"]
    fm = b.fontMetrics()
    need = b.iconSize().width() + fm.horizontalAdvance(b.text()) + 14 + 12     # icon + text + arrow + gaps
    assert b.sizeHint().width() >= need
    assert b.objectName() == "tablebtn"
