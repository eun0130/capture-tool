"""기호 tool: pick a symbol, click to stamp it there, drag while pressed to put it where it goes;
later a double-click picks it up again (move, colour, size)."""
import cv2
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.app.render import compose
from capture_tool.core.settings import Settings, load
from capture_tool.core.symbols import QUICK, all_symbols
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _open(c, tool="symbol"):
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.set_tool(tool)
    return ov


def test_ST_01_a_click_stamps_the_symbol_centred_there_a_drag_puts_it_elsewhere(make):
    c = make()
    ov = _open(c)
    tb = ov.toolbar
    assert tb.tool == "symbol" and tb.symbol == "★" and tb.buttons["symbol"].isVisible()
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    doc = c.session.document
    assert len(doc.shapes) == 1
    s = doc.shapes[0]
    assert s.kind == "text" and s.text == "★" and s.color == tb.color and s.font_size == tb.font_size
    x1, y1, x2, y2 = s.bbox()
    assert abs((x1 + x2) / 2 - 100) < 8 and abs((y1 + y2) / 2 - 100) < 8          # centred on the click
    drag(ov, (300, 250), (350, 300))                                                 # press, drag, release
    assert len(doc.shapes) == 2 and doc.shapes[1].text == "★"
    x1, y1, x2, y2 = doc.shapes[1].bbox()
    assert abs((x1 + x2) / 2 - 250) < 8 and abs((y1 + y2) / 2 - 200) < 8            # where the mouse let go
    assert doc.undo() and len(doc.shapes) == 1                                       # one step, not stamp + move


def test_ST_02_pressing_on_a_stamp_moves_it_instead_of_adding_one(make):
    c = make()
    ov = _open(c)
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    doc = c.session.document
    drag(ov, (200, 200), (260, 230))
    assert len(doc.shapes) == 1
    x1, y1, x2, y2 = doc.shapes[0].bbox()
    assert abs((x1 + x2) / 2 - 160) < 8 and abs((y1 + y2) / 2 - 130) < 8
    QTest.mouseDClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(260, 230))         # pick it up for good
    assert ov.tool == "select" and ov.selected == 0 and len(doc.shapes) == 1       # no stray stamp from the first click
    ov.toolbar.set_color("#228BE6")
    assert doc.shapes[0].color == "#228BE6"
    ov.toolbar.set_font_size(48)
    assert doc.shapes[0].font_size == 48


def test_ST_03_the_picker_sets_the_stamp_and_changes_a_selected_one(make):
    c = make()
    ov = _open(c)
    tb = ov.toolbar
    assert len(tb.quick_buttons) == len(QUICK) and tb.quick_buttons[0].isChecked()
    tb.choose_symbol("✓")
    assert tb.symbol == "✓" and ov._editor is None and ov.tool == "symbol"       # no text box opens
    assert not tb.quick_buttons[0].isChecked()
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    doc = c.session.document
    assert doc.shapes[0].text == "✓"
    QTest.mouseDClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    assert ov.selected == 0
    tb.choose_symbol("→")
    assert doc.shapes[0].text == "→" and len(doc.shapes) == 1
    tb.quick_buttons[2].click()
    assert tb.symbol == QUICK[2]


def test_ST_04_shortcut_s_and_the_symbol_group_show_only_for_the_tool(make):
    c = make()
    ov = _open(c, tool="rect")
    tb = ov.toolbar
    assert not tb.buttons["symbol"].isVisible() and not tb.quick_buttons[0].isVisible()
    QTest.keyClick(ov, Qt.Key_S)
    assert ov.tool == "symbol" and tb.buttons["symbol"].isVisible() and tb.quick_buttons[0].isVisible()
    assert tb.font_spin.isVisible() and not tb.buttons["bold"].isVisible()        # size yes, text styling no
    ov.set_tool("text")
    assert tb.buttons["symbol"].isVisible() and tb.buttons["bold"].isVisible() and not tb.quick_buttons[0].isVisible()


def test_ST_05_the_stamp_is_in_the_picture_and_the_choice_is_remembered(make):
    c = make()
    ov = _open(c)
    ov.toolbar.set_color("#E03131")
    ov.toolbar.set_font_size(40)
    ov.toolbar.choose_symbol("●")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    out = compose(np.full((300, 400, 3), 255, np.uint8), c.session.document)
    patch = out[80:120, 80:120]
    assert ((patch[:, :, 2] > 150) & (patch[:, :, 0] < 120)).sum() > 200          # red ink around (100, 100)
    QTest.keyClick(ov, Qt.Key_Return)
    saved, _ = load(c.settings_path)
    assert saved.last_symbol == "●" and saved.last_tool == "symbol"
    c2 = make(settings=saved)
    ov2 = _open(c2)
    assert ov2.toolbar.symbol == "●"


def test_ST_06_a_bad_remembered_symbol_falls_back(tmp_path):
    (tmp_path / "s.json").write_text('{"last_symbol": "ab", "last_tool": "symbol"}', encoding="utf-8")
    s, _ = load(tmp_path / "s.json")
    assert s.last_symbol == "★" and s.last_tool == "symbol"
    assert set(QUICK) <= set(all_symbols()) and Settings().last_symbol in all_symbols()


def test_ST_07_the_picker_offers_every_symbol_and_fits_on_a_screen(qt_app):
    from PySide6.QtWidgets import QToolButton
    from capture_tool.app.toolbar import Toolbar
    tb = Toolbar(None)
    pop = tb.symbols
    pop.adjustSize()
    assert pop.height() <= 420 and pop.width() <= 700                      # one tab per group, not one long grid
    offered = {b.text() for b in pop.findChildren(QToolButton) if b.text()}   # the tab bar has its own blank ones
    assert offered == set(all_symbols())
    assert pop.tabs.count() >= 9 and pop.tabs.tabText(0) == "도형"


def test_ST_08_every_symbol_stamps_in_the_pen_colour(qt_app):
    """Windows draws some characters as colour emoji whatever the font (⬅ ⌛ ⚽): those are not
    offered, because a stamp must be the colour the person chose."""
    from capture_tool.core.annotations import DEFAULT_FONT, Document, Shape
    wrong = []
    for ch in all_symbols():
        doc = Document(80, 80)
        doc.add(Shape(kind="text", points=[(10, 10)], text=ch, color="#E03131", font_size=40, font_family=DEFAULT_FONT))
        out = compose(np.full((80, 80, 3), 255, np.uint8), doc)
        px = out[(out != 255).any(axis=2)].astype(int)
        if len(px) == 0 or ((px[:, 0] > px[:, 2] + 50) | (px[:, 1] > px[:, 2] + 50)).mean() > 0.1:
            wrong.append(ch)
    assert wrong == []
