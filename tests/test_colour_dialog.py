"""The custom colour picker must appear above the capture (BUG-116): the overlay stays on top of
every window, so an ordinary dialog opened behind it - invisible, yet holding every key."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QColorDialog

from capture_tool.app.toolbar import colour_dialog
from tests.test_app import drag, make  # noqa: F401 (fixture)


def test_CD_01_colour_dialog_is_on_top_and_owned_by_the_overlay(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    dlg = colour_dialog(ov.toolbar, "#E03131", "색 선택")
    assert dlg.parent() is ov                                 # the top-level overlay, not the popup
    assert bool(dlg.windowFlags() & Qt.WindowStaysOnTopHint)
    assert dlg.testOption(QColorDialog.DontUseNativeDialog)   # the native picker ignores the flag
    assert dlg.currentColor().name().upper() == "#E03131"
    dlg.deleteLater()


def test_CD_02_the_palette_button_sets_the_colour_from_the_dialog(make, monkeypatch):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    tb = ov.toolbar
    made = []

    def fake(parent, start, title):
        dlg = colour_dialog(parent, start, title)
        dlg.setCurrentColor("#1971C2")
        dlg.exec = lambda: (dlg.accept(), QColorDialog.Accepted)[1]   # as if the person pressed OK
        made.append(dlg)
        return dlg
    monkeypatch.setattr("capture_tool.app.toolbar.colour_dialog", fake)
    tb.palette._custom()
    assert tb.color == "#1971C2" and made and made[0].parent() is ov
