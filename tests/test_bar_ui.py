"""The bar on screen: favourites first, the rest in groups under 전체, right-click to rearrange,
one arrangement per place, a 집/회사 switch, the settings page for it."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core import bar_layout as bl
from capture_tool.core.settings import Settings, load
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _open(c):
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    return ov, ov.side_bar


def _menu_action(menu, key):
    return next(a for a in menu.actions() if a.data() == key)


def test_BU_01_the_bar_shows_favourites_then_groups_with_labels(make):
    c = make(settings=Settings(bar_expanded=True))
    ov, sb = _open(c)
    assert sb.layout_first == ["copy", "autosave", "text", "translate", "summarize", "table", "ppt", "mail", "kakao", "search", "pin", "more"]
    assert [g for g, _ in sb.layout_groups] == ["저장", "보내기", "그림 손질", "화면"]
    assert [lb.text() for lb in sb.group_labels] == ["저장", "보내기", "그림 손질", "화면"]
    assert all(sb.buttons[n].isVisible() for n in sb.layout_first)
    assert sb.buttons["pdf"].isVisible() and sb.buttons["pdf"].mapTo(sb, QPoint(0, 0)).y() > sb.buttons["copy"].y()   # the second row
    assert sb.place_label.isVisible() is False                                                 # at home: no badge


def test_BU_02_right_click_takes_a_button_off_the_favourites_and_remembers_it(make, tmp_path):
    c = make()
    ov, sb = _open(c)
    m = sb.bar_menu("kakao")
    keys = [a.data() for a in m.actions() if a.data()]
    assert keys[:3] == ["bar:fav_remove:kakao", "bar:left:kakao", "bar:right:kakao"] and "bar:hide:kakao" in keys and "bar:reset" in keys
    _menu_action(m, "bar:fav_remove:kakao").trigger()
    assert "kakao" not in sb.layout_first and sb.buttons["kakao"].isVisible() is False    # the 전체 row is folded
    assert ("보내기", ["ppt_shapes", "kakao", "print", "pdf"]) in sb.layout_groups        # back in its group, in group order
    saved, _ = load(c.settings_path)
    assert "kakao" not in bl.profile_of(saved, "home").favourites
    m = sb.bar_menu("kakao")
    assert [a.data() for a in m.actions() if a.data()][0] == "bar:fav_add:kakao"          # now it can go back
    _menu_action(m, "bar:fav_add:kakao").trigger()
    assert sb.layout_first[-2] == "kakao"                                                   # at the end of the favourites


def test_BU_03_left_right_hide_and_reset(make):
    c = make()
    ov, sb = _open(c)
    _menu_action(sb.bar_menu("search"), "bar:left:search").trigger()
    assert sb.layout_first.index("search") < sb.layout_first.index("kakao")
    _menu_action(sb.bar_menu("search"), "bar:right:search").trigger()
    assert sb.layout_first.index("search") > sb.layout_first.index("kakao")
    _menu_action(sb.bar_menu("kakao"), "bar:hide:kakao").trigger()
    assert "kakao" not in sb.layout_first and "kakao" not in [n for _, ns in sb.layout_groups for n in ns]
    assert sb.buttons["kakao"].isVisible() is False and "카톡" in c.messages[-1]
    copy_keys = [a.data() for a in sb.bar_menu("copy").actions() if a.data()]
    assert copy_keys == ["bar:reset"]                                                       # copy and 전체 stay put
    _menu_action(sb.bar_menu("copy"), "bar:reset").trigger()
    assert sb.layout_first == bl.rows(bl.default_profile("home"))[0]
    assert bl.profile_of(c.settings, "home") == bl.default_profile("home")


def test_BU_04_a_right_click_on_the_bar_opens_the_menu_for_that_button(make, monkeypatch):
    c = make()
    ov, sb = _open(c)
    opened = []
    monkeypatch.setattr(sb, "_show_bar_menu", lambda name, pos: opened.append(name))
    b = sb.buttons["mail"]
    QTest.mouseClick(b, Qt.RightButton, Qt.NoModifier, QPoint(5, 5))
    assert opened == ["mail"]


def test_BU_05_each_place_has_its_own_bar_and_the_switch_shows_a_badge(make):
    c = make()
    ov, sb = _open(c)
    c.set_workplace("work")
    assert c.settings.workplace == "work" and "회사" in c.messages[-1]
    assert "kakao" not in sb.layout_first and sb.buttons["kakao"].isVisible() is False
    assert "mail" not in sb.layout_first and sb.buttons["mail"].isVisible() is False      # neither works at the office
    assert sb.place_label.isVisible() and sb.place_label.text() == "회사"
    _menu_action(sb.bar_menu("pdf"), "bar:fav_add:pdf").trigger()
    assert "pdf" in bl.profile_of(c.settings, "work").favourites and "pdf" not in bl.profile_of(c.settings, "home").favourites
    c.set_workplace("home")
    assert "kakao" in sb.layout_first and "mail" in sb.layout_first and "pdf" not in sb.layout_first and sb.place_label.isVisible() is False
    c.set_workplace("moon")
    assert c.settings.workplace == "home"


def test_BU_06_the_edit_window_column_follows_the_same_order(make):
    import numpy as np
    c = make()
    bl.store_profile(c.settings, "home", bl.add_favourite(bl.remove_favourite(bl.default_profile("home"), "mail"), "pdf"))
    c.open_editor(np.full((300, 400, 3), 200, np.uint8), 96.0, "시험")
    sb = c.editor.canvas.side_bar
    order = sb.column_order                                       # the column, top to bottom
    assert all(sb.buttons[n].isVisible() for n in order)
    assert order[:3] == ["copy", "text", "translate"] and order.index("pdf") < order.index("save_as") < order.index("mail")
    assert "scroll" not in order and "more" not in order and "autosave" not in order


def test_BU_07_settings_page_edits_the_profiles(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    s = Settings()
    d = SettingsDialog(s)
    assert d.place_home.isChecked() and [d.fav_list.item(i).data(Qt.UserRole) for i in range(d.fav_list.count())] == bl.default_profile("home").favourites
    rest = [d.rest_list.item(i).data(Qt.UserRole) for i in range(d.rest_list.count()) if d.rest_list.item(i).data(Qt.UserRole)]
    assert rest == [n for _, ns in bl.rows(bl.default_profile("home"))[1] for n in ns]
    d.fav_list.setCurrentRow(d.fav_list.count() - 1)            # pin
    d._fav_move(-1)
    d._fav_remove()                                              # pin (moved up one) comes off
    d.rest_list.setCurrentItem(next(d.rest_list.item(i) for i in range(d.rest_list.count()) if d.rest_list.item(i).data(Qt.UserRole) == "pdf"))
    d._fav_add()
    pdf_item = next(d.rest_list.item(i) for i in range(d.rest_list.count()) if d.rest_list.item(i).data(Qt.UserRole) == "print")
    pdf_item.setCheckState(Qt.Checked)                           # hide 인쇄 at home
    d.place_work.setChecked(True)                                # the other place: its own lists
    assert "kakao" not in [d.fav_list.item(i).data(Qt.UserRole) for i in range(d.fav_list.count())]
    out = d.result_settings()
    home = bl.profile_of(out, "home")
    assert "pin" not in home.favourites and home.favourites[-1] == "pdf" and home.hidden == ["print"]
    assert out.workplace == "work" and bl.profile_of(out, "work") == bl.default_profile("work")
    d._bar_defaults()
    assert bl.profile_of(d.result_settings(), "home") == bl.default_profile("home")


def test_BU_08_the_whole_row_wraps_on_a_narrow_screen(make):
    """A 1366-px laptop at 125% is ~1090 logical px: the grouped 전체 buttons no longer fit one row."""
    c = make(settings=Settings(bar_expanded=True))
    ov, sb = _open(c)
    c.apply_bar_layout(sb, 10_000)
    assert sb._extra_rows.count() == 1
    c.apply_bar_layout(sb, 600)
    assert sb._extra_rows.count() >= 2
    rest = [sb.buttons[n] for _, ns in sb.layout_groups for n in ns]
    assert all(b.isVisible() and b.mapTo(sb, QPoint(0, 0)).x() + b.width() <= 620 for b in rest)
    assert len({b.mapTo(sb, QPoint(0, 0)).y() for b in rest}) >= 2
