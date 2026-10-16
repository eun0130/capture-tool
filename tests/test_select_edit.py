"""Drawings stay editable: double-click picks a shape with any tool (move it, restyle it);
double-click a text to change its words."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_app import drag, make  # noqa: F401 (fixture)


def _setup(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    ov.set_tool("rect")
    drag(ov, (120, 120), (200, 160))                       # shape 0: a box
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(300, 300))
    ov._editor.setText("hello")
    QTest.keyClick(ov._editor, Qt.Key_Return)              # shape 1: a text
    ov.set_tool("rect")
    return c, ov


def _dclick(w, x, y):
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseDClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))


def test_SEL_01_double_click_picks_a_shape_with_any_tool_then_it_moves(make):
    c, ov = _setup(make)
    doc = c.session.document
    assert [s.kind for s in doc.shapes] == ["rect", "text"]
    _dclick(ov, 160, 140)                                  # on the box, while the rect tool is active
    assert ov.tool == "select" and ov.selected == 0
    assert len(doc.shapes) == 2                            # the clicks did not add a tiny box
    before = doc.shapes[0].points
    drag(ov, (160, 140), (260, 190))                       # drag it 100 right, 50 down
    assert doc.shapes[0].points == [(x + 100, y + 50) for x, y in before]
    ov.set_color("#1971C2")                                # restyle the picked shape
    ov._style_changed("color")
    assert doc.shapes[0].color == "#1971C2"


def test_SEL_02_double_click_a_text_to_change_its_words(make):
    c, ov = _setup(make)
    doc = c.session.document
    pt = doc.shapes[1].points[0]
    doc.update(1, bold=True)
    _dclick(ov, 310, 305)
    assert ov._editor is not None and ov._editor.text() == "hello" and ov._editor.edit_index == 1
    ov._editor.setText("hello world")
    QTest.keyClick(ov._editor, Qt.Key_Return)
    assert ov._editor is None
    assert [s.kind for s in doc.shapes] == ["rect", "text"]            # changed in place, not added
    assert doc.shapes[1].text == "hello world" and doc.shapes[1].points[0] == pt and doc.shapes[1].bold
    assert doc.undo() and doc.shapes[1].text == "hello"                # one step to take back


def test_SEL_03_escape_keeps_the_text_as_it_was(make):
    c, ov = _setup(make)
    doc = c.session.document
    _dclick(ov, 310, 305)
    ov._editor.setText("something else")
    QTest.keyClick(ov._editor, Qt.Key_Escape)                        # clears the box ...
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(450, 380))   # ... a click elsewhere closes it
    assert ov._editor is None and doc.shapes[1].text == "hello"


def test_SEL_04_double_click_on_nothing_changes_nothing(make):
    c, ov = _setup(make)
    _dclick(ov, 450, 380)
    assert ov.tool == "rect" and ov.selected is None and ov._editor is None
    assert len(c.session.document.shapes) == 2


def test_SEL_05_a_step_number_is_picked_and_moved_too(make):
    c, ov = _setup(make)
    doc = c.session.document
    ov.set_tool("step")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(400, 200))
    assert doc.shapes[-1].kind == "step"
    _dclick(ov, 400, 200)                                  # the first click of the two adds no number
    assert ov.selected == 2 and len(doc.shapes) == 3
    drag(ov, (400, 200), (420, 230))
    assert doc.shapes[2].points[0] == (320, 130)
