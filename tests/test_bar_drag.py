"""Rearranging the action bar by dragging: a favourite dragged along the first row lands where
the blue line was; a 전체 button dragged up joins the favourites; a favourite dragged down onto
the 전체 rows leaves them; outside the bar is a cancel; the fixed ends never move; a plain click
still works. The edit window's column and the settings lists drag the same way."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from capture_tool.core import bar_layout as bl
from capture_tool.core.settings import Settings, load
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _open(c, expanded=False):
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    if expanded:
        ov.side_bar.trigger("more")
    return ov, ov.side_bar


def _centre(sb, name):
    b = sb.buttons[name]
    return b.mapTo(sb, b.rect().center())


def _drag_to(sb, name, to, steps=4):
    """Press `name`, move to `to` (side-bar coordinates) in steps, release there."""
    src = sb.buttons[name]
    start = src.rect().center()
    end = src.mapFrom(sb, to)
    QTest.mousePress(src, Qt.LeftButton, Qt.NoModifier, start)
    for i in range(1, steps + 1):
        t = i / steps
        QTest.mouseMove(src, QPoint(int(start.x() + (end.x() - start.x()) * t), int(start.y() + (end.y() - start.y()) * t)))
    QTest.mouseRelease(src, Qt.LeftButton, Qt.NoModifier, end)


def _wire(sb):
    fired = []
    sb.action.connect(fired.append)
    return fired


pytestmark = pytest.mark.windows_contract


def test_BD_01_a_favourite_dragged_along_the_row_lands_after_the_button_before_the_line(make):
    c = make()
    ov, sb = _open(c)
    fired = _wire(sb)
    before = list(sb.layout_first)
    to = _centre(sb, "kakao") + QPoint(12, 0)                  # right of 카톡's middle: the slot after it
    _drag_to(sb, "translate", to)
    assert fired == ["bar:fav_after:translate:kakao"]
    assert sb.layout_first.index("translate") == sb.layout_first.index("kakao") + 1
    assert sorted(sb.layout_first) == sorted(before)
    saved, _ = load(c.settings_path)
    assert bl.profile_of(saved, "home").favourites == [n for n in sb.layout_first if n not in ("copy", "more")]
    assert sb.dragging() is False and sb.buttons["translate"].isDown() is False
    to = _centre(sb, "autosave") - QPoint(12, 0)               # left of 자동저장's middle: right after 복사
    _drag_to(sb, "translate", to)
    assert fired[-1] == "bar:fav_after:translate:copy" and sb.layout_first[1] == "translate"


def test_BD_02_a_short_press_is_a_click_and_the_fixed_ends_do_not_drag(make):
    c = make()
    ov, sb = _open(c)
    fired = _wire(sb)
    b = sb.buttons["autosave"]
    QTest.mousePress(b, Qt.LeftButton, Qt.NoModifier, b.rect().center())
    QTest.mouseMove(b, b.rect().center() + QPoint(3, 1))       # under the 6-px threshold: no drag
    QTest.mouseRelease(b, Qt.LeftButton, Qt.NoModifier, b.rect().center() + QPoint(3, 1))
    assert fired == ["autosave"]
    before = list(sb.layout_first)
    _drag_to(sb, "copy", _centre(sb, "mail"))                  # 복사 stays first
    _drag_to(sb, "more", _centre(sb, "text"))                  # 전체 stays last
    assert fired == ["autosave"] and sb.layout_first == before and sb.dragging() is False


def test_BD_03_dropping_outside_the_bar_cancels(make):
    c = make()
    ov, sb = _open(c)
    fired = _wire(sb)
    before = list(sb.layout_first)
    _drag_to(sb, "translate", QPoint(sb.width() // 2, -120))
    assert fired == [] and sb.layout_first == before
    assert sb.ghost is None or not sb.ghost.isVisible()
    assert bl.profile_of(c.settings, "home") == bl.default_profile("home")


def test_BD_04_a_whole_row_button_dragged_up_joins_the_favourites_there(make):
    c = make(settings=Settings(bar_expanded=True))
    ov, sb = _open(c)
    fired = _wire(sb)
    assert "pdf" not in sb.layout_first and sb.buttons["pdf"].isVisible()
    _drag_to(sb, "pdf", _centre(sb, "search") + QPoint(12, 0))
    assert fired == ["bar:fav_after:pdf:search"]
    assert sb.layout_first.index("pdf") == sb.layout_first.index("search") + 1
    assert "pdf" not in [n for _, ns in sb.layout_groups for n in ns]
    assert "'PDF'" in c.messages[-1] and "즐겨찾기" in c.messages[-1]


def test_BD_05_a_favourite_dragged_down_onto_the_whole_rows_leaves_the_favourites(make):
    c = make(settings=Settings(bar_expanded=True))
    ov, sb = _open(c)
    fired = _wire(sb)
    _drag_to(sb, "summarize", _centre(sb, "pdf"))
    assert fired == ["bar:fav_remove:summarize"]
    assert "summarize" not in sb.layout_first
    assert ("글자·표", ["summarize"]) in sb.layout_groups        # back in its own group, whatever it was dropped on
    before = list(sb.layout_first)
    _drag_to(sb, "pdf", _centre(sb, "print"))                  # within the 전체 rows: nothing to arrange there
    assert fired == ["bar:fav_remove:summarize"] and sb.layout_first == before


def test_BD_06_the_edit_window_column_drags_up_and_down(make):
    import numpy as np
    c = make()
    c.open_editor(np.full((300, 400, 3), 200, np.uint8), 96.0, "시험")
    sb = c.editor.canvas.side_bar
    fired = _wire(sb)
    assert sb.columns == 1
    _drag_to(sb, "translate", _centre(sb, "ppt") + QPoint(0, 10))
    assert fired == ["bar:fav_after:translate:ppt"]
    assert sb.column_order.index("translate") == sb.column_order.index("ppt") + 1
    _drag_to(sb, "save_as", _centre(sb, "text") - QPoint(0, 10))        # a group button up into the favourites
    assert fired[-1] == "bar:fav_after:save_as:copy" and sb.column_order[1] == "save_as"
    _drag_to(sb, "save_as", _centre(sb, "pdf"))                          # and down again
    assert fired[-1] == "bar:fav_remove:save_as" and sb.column_order.index("save_as") > sb.column_order.index("pin")


def test_BD_07_the_settings_lists_drag_too(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    d = SettingsDialog(Settings())
    assert d.fav_list.dragDropMode() == QAbstractItemView.InternalMove
    assert d.fav_list.defaultDropAction() == Qt.MoveAction
    it = d.fav_list.takeItem(0)                                           # what a drop does inside the list
    d.fav_list.insertItem(2, it)
    assert bl.profile_of(d.result_settings(), "home").favourites[:3] == ["text", "translate", "autosave"]
