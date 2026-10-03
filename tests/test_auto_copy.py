"""Choosing an area copies it right away (Ctrl+V works without Ctrl+C); drawing keeps the
clipboard up to date; Ctrl+C still copies; the setting turns it off."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import PNG, UNICODE
from tests.test_app import FakeOcr, decode_png, drag, make  # noqa: F401 (fixture)


def pngs(c):
    return [p[PNG] for p in c.clipboard.payloads if PNG in p]


def test_AUTO_01_selecting_an_area_copies_it_at_once(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert c.overlays and len(pngs(c)) == 1                   # still editing, already on the clipboard
    img = decode_png(pngs(c)[0])
    assert img.shape[1] > 300 and img.shape[0] > 200


def test_AUTO_02_drawing_updates_the_clipboard(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    first = pngs(c)[-1]
    ov.set_tool("rect")
    drag(ov, (150, 150), (300, 300))
    c.flush_auto_copy()
    assert pngs(c)[-1] != first                               # the drawn box is in the copy


def test_AUTO_03_ctrl_c_still_copies_and_closes(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    n = len(pngs(c))
    QTest.keyClick(ov, Qt.Key_C, Qt.ControlModifier)
    assert len(pngs(c)) == n + 1 and c.overlays == []


def test_AUTO_04_setting_off_waits_for_ctrl_c(make):
    c = make()
    c.settings.auto_copy = False
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert pngs(c) == []
    QTest.keyClick(ov, Qt.Key_C, Qt.ControlModifier)
    assert len(pngs(c)) == 1


def test_AUTO_05_escape_keeps_what_was_copied(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    QTest.keyClick(ov, Qt.Key_Escape)
    QTest.keyClick(ov, Qt.Key_Escape)
    assert len(pngs(c)) == 1                                  # nothing cleared or replaced


def test_AUTO_06_text_mode_copies_text_not_the_picture(make):
    from capture_tool.core.ocr import OcrLine
    c = make(ocr=FakeOcr([OcrLine("글자", (10, 10, 60, 20), 0.99)]))
    c.start_capture(mode="text")
    drag(c.overlays[0], (100, 100), (400, 300))
    assert pngs(c) == [] and "글자" in c.clipboard.last[UNICODE]


def test_AUTO_07_moving_the_area_with_arrow_keys_recopies(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    n = len(pngs(c))
    c.nudge(10, 0)
    c.flush_auto_copy()
    assert len(pngs(c)) == n + 1


def test_AUTO_08_setting_is_saved(tmp_path):
    from capture_tool.core.settings import Settings, load, save
    s = Settings()
    assert s.auto_copy is True and s.keep_style is True
    s.auto_copy, s.keep_style = False, False
    save(s, tmp_path / "s.json")
    back, _ = load(tmp_path / "s.json")
    assert back.auto_copy is False and back.keep_style is False


def test_AUTO_09_settings_dialog_has_both_switches(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    from capture_tool.core.settings import Settings
    d = SettingsDialog(Settings())
    assert d.auto_copy.isChecked() and d.keep_style.isChecked()
    d.auto_copy.setChecked(False)
    d.keep_style.setChecked(False)
    s = d.result_settings()
    assert s.auto_copy is False and s.keep_style is False
    d._defaults()
    assert d.auto_copy.isChecked() and d.keep_style.isChecked()
