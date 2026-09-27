"""UI behavior tests (headless Qt). Mouse/keyboard are simulated with QTest."""
import io
import zipfile

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import DIB, GVML, PNG, SVG, UNICODE
from capture_tool.core.geometry import Monitor, Rect
from capture_tool.core.ocr import OcrLine
from capture_tool.core.settings import Settings
from capture_tool.platform.windows import WindowInfo
from tests import synth

MON_A = Monitor(0, Rect(0, 0, 800, 600), 1.0, True, "A")
MON_B = Monitor(1, Rect(800, 0, 800, 600), 1.0, False, "B")


class FakeScreen:
    def __init__(self, cursor=(100, 100), monitors=(MON_A,), image=None, wins=()):
        self.cursor = cursor
        self.mons = list(monitors)
        self.image = image
        self.wins = list(wins)
        self.grabs = []

    def monitors(self):
        return self.mons

    def cursor_pos(self):
        return self.cursor

    def grab(self, r):
        self.grabs.append(r)
        if self.image is not None:
            return self.image[r.y:r.y + r.h, r.x - (r.x // 800) * 800:][:, :r.w].copy()
        img = np.full((r.h, r.w, 3), 255, np.uint8)
        return img

    def windows(self):
        return self.wins


class FakeClipboard:
    def __init__(self):
        self.payloads = []

    def set(self, payload):
        self.payloads.append(payload)

    @property
    def last(self):
        return self.payloads[-1]


class FakeOcr:
    def __init__(self, lines=()):
        self.lines = list(lines)
        self.ready = True

    def recognize(self, img):
        return self.lines

    def warmup(self):
        pass


@pytest.fixture
def make(qt_app, tmp_path):
    from capture_tool.app.controller import Controller
    made = []

    def _make(screen=None, ocr=None, settings=None):
        c = Controller(screen=screen or FakeScreen(), clipboard=FakeClipboard(), ocr=ocr or FakeOcr(),
                       settings=settings or Settings(save_dir=str(tmp_path / "shots")),
                       settings_path=tmp_path / "settings.json", fallback_dir=tmp_path / "fallback",
                       sync=True)
        made.append(c)
        return c

    yield _make
    for c in made:
        c.close_all()


def drag(w, a, b):
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, QPoint(*a))
    for t in (0.3, 0.6, 1.0):
        QTest.mouseMove(w, QPoint(int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t)))
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(*b))


def decode_png(data):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


# --- capture start & multi-monitor -------------------------------------------

def test_APP_01_cursor_monitor_first(make):
    c = make(FakeScreen(cursor=(1000, 300), monitors=[MON_A, MON_B]))
    assert c.start_capture()
    assert c.screen.grabs[0] == MON_B.rect          # cursor monitor grabbed first
    assert c.overlays[0].monitor is MON_B
    assert {o.monitor.name for o in c.overlays} == {"A", "B"}
    assert c.overlays[0].isActiveWindow() or c.overlays[0].hasFocus() or c.overlays[0].isVisible()


def test_APP_02_second_hotkey_ignored(make):
    c = make()
    assert c.start_capture()
    assert not c.start_capture()
    assert len(c.overlays) == 1


def test_APP_03_drag_shows_toolbar_inside_monitor(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    assert c.session.selection == Rect(100, 100, 300, 200)
    tb = ov.toolbar
    assert tb.isVisible()
    assert tb.geometry().top() >= 300 and tb.geometry().right() <= 800


def test_APP_04_escape_cancels(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    QTest.keyClick(ov, Qt.Key_Escape)
    assert c.overlays == []
    assert c.clipboard.payloads == []


# --- drawing & copy ----------------------------------------------------------

def test_APP_05_draw_rect_then_enter_copies_image_with_annotation(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.set_tool("rect")
    ov.set_color("#E03131")
    drag(ov, (150, 150), (250, 250))
    assert len(c.session.document.shapes) == 1
    QTest.keyClick(ov, Qt.Key_Return)
    p = c.clipboard.last
    assert list(p)[:2] == [PNG, DIB]
    img = decode_png(p[PNG])
    assert img.shape[:2] == (200, 300)
    b, g, r = img[50, 60]                           # rect edge at (50,50)-(150,150) in crop coords
    assert r > 180 and g < 100 and b < 100
    assert c.overlays == []


def test_APP_06_undo_redo_keys(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.set_tool("ellipse")
    drag(ov, (150, 150), (250, 250))
    QTest.keyClick(ov, Qt.Key_Z, Qt.ControlModifier)
    assert c.session.document.shapes == []
    QTest.keyClick(ov, Qt.Key_Y, Qt.ControlModifier)
    assert len(c.session.document.shapes) == 1


def test_APP_07_step_tool_numbers(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.set_tool("step")
    for x in (150, 200, 250):
        QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(x, 150))
    assert [s.number for s in c.session.document.shapes] == [1, 2, 3]


def test_APP_08_tool_shortcut_keys(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    QTest.keyClick(ov, Qt.Key_O)
    assert ov.tool == "ellipse"
    QTest.keyClick(ov, Qt.Key_A)
    assert ov.tool == "arrow"


def test_APP_09_arrow_keys_nudge_selection(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    QTest.keyClick(ov, Qt.Key_Right)
    QTest.keyClick(ov, Qt.Key_Down)
    assert c.session.selection == Rect(101, 101, 300, 200)


# --- save ----------------------------------------------------------------------

def test_APP_10_save_to_folder_with_unique_names(make, tmp_path):
    from datetime import datetime
    c = make()
    c.now = lambda: datetime(2026, 9, 26, 14, 30, 12)
    for _ in range(2):
        c.start_capture()
        ov = c.overlays[0]
        drag(ov, (10, 10), (110, 60))
        QTest.keyClick(ov, Qt.Key_S, Qt.ControlModifier)
    files = sorted(p.name for p in (tmp_path / "shots").iterdir())
    assert len(files) == 2 and files[0].startswith("Capture_") and files[1].endswith("_1.png")
    img = cv2.imread(str(tmp_path / "shots" / files[0]))
    assert img.shape[:2] == (50, 100)


def test_APP_11_save_falls_back_when_folder_invalid(make, tmp_path):
    c = make(settings=Settings(save_dir="Z:\\no\\such\\drive"))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (10, 10), (110, 60))
    QTest.keyClick(ov, Qt.Key_S, Qt.ControlModifier)
    assert len(list((tmp_path / "fallback").iterdir())) == 1
    assert any("대체" in m for m in c.messages)


def test_APP_12_auto_save_on_copy(make, tmp_path):
    c = make(settings=Settings(save_dir=str(tmp_path / "auto"), auto_save=True))
    c.start_capture()
    drag(c.overlays[0], (10, 10), (110, 60))
    QTest.keyClick(c.overlays[0], Qt.Key_Return)
    assert len(list((tmp_path / "auto").iterdir())) == 1
    assert PNG in c.clipboard.last


def test_APP_13_jpg_format(make, tmp_path):
    c = make(settings=Settings(save_dir=str(tmp_path / "j"), image_format="jpg"))
    c.start_capture()
    drag(c.overlays[0], (10, 10), (110, 60))
    QTest.keyClick(c.overlays[0], Qt.Key_S, Qt.ControlModifier)
    assert [p.suffix for p in (tmp_path / "j").iterdir()] == [".jpg"]


# --- text mode -----------------------------------------------------------------

def test_APP_14_text_mode_copies_ocr_text_with_pii_masked(make):
    lines = [OcrLine("견적 요약", (10, 10, 100, 20), 0.99), OcrLine("담당 010-1234-5678", (10, 40, 180, 20), 0.98)]
    c = make(ocr=FakeOcr(lines))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.toolbar.trigger("text")
    text = c.clipboard.last[UNICODE]
    assert "견적 요약" in text
    assert "010-1234-5678" not in text and "***" in text
    # the capture stays open so the user can drag over part of the text
    assert c.overlays == [ov] and ov.ocr_lines and ov.ocr_bar.isVisible()


def test_APP_15_text_mode_pii_off(make):
    lines = [OcrLine("담당 010-1234-5678", (10, 40, 180, 20), 0.98)]
    c = make(ocr=FakeOcr(lines), settings=Settings(redact_pii=False))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].toolbar.trigger("text")
    assert "010-1234-5678" in c.clipboard.last[UNICODE]


def test_APP_16_text_mode_no_text_found(make):
    c = make(ocr=FakeOcr([]))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].toolbar.trigger("text")
    assert c.clipboard.payloads == []
    assert any("텍스트를 찾지 못" in m for m in c.messages)


def test_APP_17_text_panel_table_copy(make):
    lines = [OcrLine("품목", (10, 10, 40, 20), 0.9), OcrLine("수량", (160, 10, 40, 20), 0.9),
             OcrLine("A", (10, 50, 20, 20), 0.9), OcrLine("3", (160, 50, 10, 20), 0.9)]
    c = make(ocr=FakeOcr(lines))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].toolbar.trigger("text")
    c.overlays[0].ocr_bar.trigger("window")        # "창으로 보기"
    assert c.overlays == [] and c.text_panel.isVisible()
    c.text_panel.copy_table()
    assert c.clipboard.last[UNICODE] == "품목\t수량\r\nA\t3"


def test_APP_18_ocr_unavailable_message(make):
    from capture_tool.core.ocr import OcrUnavailable

    class Broken(FakeOcr):
        def recognize(self, img):
            raise OcrUnavailable("모델 없음")

    c = make(ocr=Broken())
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].toolbar.trigger("text")
    assert any("모델 없음" in m for m in c.messages)


# --- shapes -> PowerPoint ------------------------------------------------------

def _flow_image():
    img = synth.canvas(800, 600)
    synth.rect(img, 120, 140, 150, 64, fill="#F1F3F5")
    synth.rect(img, 340, 140, 150, 64, fill="#F1F3F5")
    synth.line(img, 272, 172, 336, 172, arrow=True)
    return img


def test_APP_19_shapes_mode_puts_native_shapes_on_clipboard(make):
    lines = [OcrLine("요청 접수", (60, 60, 80, 20), 0.99), OcrLine("검토", (285, 60, 40, 20), 0.99)]
    c = make(screen=FakeScreen(image=_flow_image()), ocr=FakeOcr(lines))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (520, 260))
    c.overlays[0].toolbar.trigger("shapes")
    p = c.clipboard.last
    assert list(p) == [GVML, SVG, PNG]
    xml = zipfile.ZipFile(io.BytesIO(p[GVML])).read("clipboard/drawings/drawing1.xml").decode("utf-8")
    assert xml.count("<a:sp>") == 2 and xml.count("<a:cxnSp>") == 1
    assert "요청 접수" in xml and "검토" in xml and "stCxn" in xml
    assert any("도형 2개" in m for m in c.messages)


def test_APP_20_shapes_mode_includes_user_drawn_shapes(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.set_tool("rect")
    drag(ov, (150, 150), (250, 250))
    ov.toolbar.trigger("shapes")
    xml = zipfile.ZipFile(io.BytesIO(c.clipboard.last[GVML])).read("clipboard/drawings/drawing1.xml").decode()
    assert xml.count("<a:sp>") == 1


def test_APP_21_shapes_mode_nothing_found(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].toolbar.trigger("shapes")
    assert c.clipboard.payloads == []
    assert any("도형을 찾지 못" in m for m in c.messages)


# --- pin -----------------------------------------------------------------------

def test_APP_22_pin_window(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    QTest.keyClick(c.overlays[0], Qt.Key_F3)
    assert len(c.pins) == 1
    pin = c.pins[0]
    assert pin.isVisible() and pin.image_size == (300, 200)
    assert pin.windowFlags() & Qt.WindowStaysOnTopHint
    QTest.mouseDClick(pin, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
    assert c.pins == []


def _pinned(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].side_bar.trigger("pin")
    assert len(c.pins) == 1
    return c, c.pins[0]


def test_APP_38_escape_closes_pin(make):
    c, pin = _pinned(make)
    QTest.keyClick(pin, Qt.Key_Escape)
    assert c.pins == [] and not pin.isVisible()


def test_APP_39_pin_takes_keyboard_focus(make):
    c, pin = _pinned(make)
    assert pin.focusPolicy() & Qt.StrongFocus
    assert pin.hasFocus() or pin.isActiveWindow() or pin._focus_requested


def test_APP_40_pin_close_button(make):
    c, pin = _pinned(make)
    btn = pin.close_button
    QTest.mouseMove(pin, QPoint(pin.width() - 10, 10))
    assert btn.isVisible()
    btn.click()
    assert c.pins == []


def test_APP_41_pin_ctrl_c_copies_and_ctrl_s_saves(make, tmp_path):
    c, pin = _pinned(make)
    QTest.keyClick(pin, Qt.Key_C, Qt.ControlModifier)
    assert PNG in c.clipboard.last
    QTest.keyClick(pin, Qt.Key_S, Qt.ControlModifier)
    assert len(list((tmp_path / "shots").iterdir())) == 1
    assert len(c.pins) == 1


def test_APP_42_close_all_pins(make):
    c, _ = _pinned(make)
    c.start_capture()
    drag(c.overlays[0], (10, 10), (110, 60))
    QTest.keyClick(c.overlays[0], Qt.Key_F3)
    assert len(c.pins) == 2
    c.close_pins()
    assert c.pins == []


def test_APP_43_pin_placed_over_the_captured_region(make):
    c, pin = _pinned(make)
    ov_geo = QPoint(0, 0)
    assert pin.geometry().topLeft() == ov_geo + QPoint(100, 100)
    assert (pin.width(), pin.height()) == (300, 200)


def test_APP_23_pin_zoom_and_opacity(make):
    c = make()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    QTest.keyClick(c.overlays[0], Qt.Key_F3)
    pin = c.pins[0]
    pin.zoom_by(1)
    assert pin.zoom > 1.0
    pin.opacity_by(-1)
    assert pin.windowOpacity() < 1.0


# --- window auto-detect & color picker -------------------------------------------

def test_APP_24_click_selects_window_under_cursor(make):
    wins = [WindowInfo(1, "메모장", Rect(50, 60, 300, 200))]
    c = make(FakeScreen(wins=wins))
    c.start_capture()
    ov = c.overlays[0]
    QTest.mouseMove(ov, QPoint(100, 100))
    assert ov.hover_window is not None
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    assert c.session.selection == Rect(50, 60, 300, 200)


def test_APP_25_color_picker_copies_hex(make):
    img = np.full((600, 800, 3), 255, np.uint8)
    img[200, 300] = (64, 58, 52)
    c = make(FakeScreen(image=img))
    c.start_capture()
    ov = c.overlays[0]
    QTest.mouseMove(ov, QPoint(300, 200))
    QTest.keyClick(ov, Qt.Key_C)
    assert c.clipboard.last[UNICODE] == "#343A40"


# --- hotkeys & settings ----------------------------------------------------------

def test_APP_26_hotkey_registration_conflict_message(make):
    from capture_tool.app.hotkeys import HotkeyManager
    mgr = HotkeyManager(register=lambda hk_id, hk: False, unregister=lambda hk_id: None)
    failures = mgr.apply({"capture": "Win + ~", "ocr": ""})
    assert list(failures) == ["capture"]
    assert "Windows Terminal" in failures["capture"]


def test_APP_27_hotkey_manager_dispatch(make):
    from capture_tool.app.hotkeys import HotkeyManager
    mgr = HotkeyManager(register=lambda hk_id, hk: True, unregister=lambda hk_id: None)
    got = []
    mgr.triggered.connect(got.append)
    assert mgr.apply({"capture": "Win + ~", "ocr": "Ctrl + Shift + 2"}) == {}
    mgr.dispatch(mgr.id_for("ocr"))
    assert got == ["ocr"]


def test_APP_28_settings_dialog_records_and_validates(qt_app, tmp_path):
    from capture_tool.app.settings_dialog import HotkeyEdit, SettingsDialog
    ed = HotkeyEdit()
    QTest.keyClick(ed, Qt.Key_3, Qt.ControlModifier | Qt.ShiftModifier)
    assert ed.text() == "Ctrl + Shift + 3"
    dlg = SettingsDialog(Settings())
    dlg.edits["ocr"].setText("Option + ~")   # same as default capture (Alt + ~)
    errors = dlg.validate()
    assert any("겹칩니다" in e for e in errors)          # duplicate of capture
    dlg.edits["ocr"].setText("Ctrl + C")
    assert any("시스템" in e for e in dlg.validate())    # reserved
    dlg.edits["ocr"].setText("Ctrl + Shift + 2")
    assert dlg.validate() == []
    s = dlg.result_settings()
    assert s.hotkeys["ocr"] == "Ctrl + Shift + 2"


def test_APP_29_direct_text_hotkey_mode(make):
    lines = [OcrLine("바로 복사", (10, 10, 100, 20), 0.99)]
    c = make(ocr=FakeOcr(lines))
    c.start_capture(mode="text")
    drag(c.overlays[0], (100, 100), (400, 300))
    assert "바로 복사" in c.clipboard.last[UNICODE]


# --- quick-action side bar ("이모티콘" next to the capture) ---------------------------

class FakePpt:
    """Stands in for PowerPointSender: records what would be inserted."""

    def __init__(self, ok=True, error=None, added=None):
        self.items = []
        self.ok = ok
        self.error = error
        self.added = added
        self.busy = False

    @property
    def calls(self):
        return len(self.items)

    def send(self, item):
        from capture_tool.platform.powerpoint import PowerPointUnavailable
        self.items.append(item)
        if self.error is not None:
            raise self.error
        if not self.ok:
            raise PowerPointUnavailable("PowerPoint가 설치되어 있지 않습니다.")
        return self.added if self.added is not None else 1


def test_APP_31_side_bar_next_to_selection(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    sb = ov.side_bar
    assert sb.isVisible()
    g = sb.geometry()
    assert g.left() >= 400 and g.top() == 100 and g.right() <= 800
    assert list(sb.buttons) == ["copy", "save_as", "text", "ppt", "ppt_shapes", "pin"]


def test_APP_32_save_icon_asks_location(make, tmp_path):
    c = make()
    target = tmp_path / "내 폴더" / "회의.png"
    target.parent.mkdir()
    asked = []
    c.ask_save_path = lambda default, parent=None: (asked.append(default), target)[1]
    c.start_capture()
    drag(c.overlays[0], (10, 10), (110, 60))
    c.overlays[0].side_bar.trigger("save_as")
    assert target.exists() and cv2.imdecode(np.fromfile(str(target), np.uint8), 1).shape[:2] == (50, 100)
    assert c.settings.last_save_dir == str(target.parent)
    assert asked[0].name.startswith("Capture_")
    assert c.overlays == []


def test_APP_33_save_dialog_cancel_keeps_capture(make):
    from capture_tool.core.session import State
    c = make()
    c.ask_save_path = lambda default, parent=None: None
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.set_tool("rect")
    drag(ov, (150, 150), (250, 250))
    ov.side_bar.trigger("save_as")
    assert c.session.state is State.EDITING and len(c.session.document.shapes) == 1
    assert c.overlays == [ov]


def test_APP_34_save_dialog_starts_in_last_folder(make, tmp_path):
    c = make(settings=Settings(last_save_dir=str(tmp_path / "last")))
    asked = []
    c.ask_save_path = lambda default, parent=None: (asked.append(default), None)[1]
    c.start_capture()
    drag(c.overlays[0], (10, 10), (110, 60))
    QTest.keyClick(c.overlays[0], Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
    assert asked[0].parent == tmp_path / "last"


def test_APP_35_shapes_button_sends_native_shapes(make):
    from capture_tool.platform.powerpoint import ClipboardShapes
    lines = [OcrLine("요청 접수", (60, 60, 80, 20), 0.99), OcrLine("검토", (285, 60, 40, 20), 0.99)]
    c = make(screen=FakeScreen(image=_flow_image()), ocr=FakeOcr(lines))
    c.powerpoint = FakePpt(added=3)
    c.start_capture()
    drag(c.overlays[0], (100, 100), (520, 260))
    c.overlays[0].side_bar.trigger("ppt_shapes")
    assert GVML in c.clipboard.last
    assert isinstance(c.powerpoint.items[0], ClipboardShapes)
    assert any("PowerPoint에 넣었습니다" in m for m in c.messages)


def test_APP_36_ppt_button_sends_the_capture_as_a_picture(make):
    from capture_tool.platform.powerpoint import Picture
    c = make()
    c.powerpoint = FakePpt()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    ov.set_tool("rect")
    drag(ov, (150, 150), (250, 250))                  # a drawing is part of "what I captured"
    ov.side_bar.trigger("ppt")
    item = c.powerpoint.items[0]
    assert isinstance(item, Picture) and item.image.shape[:2] == (200, 300)
    b, g, r = item.image[50, 60]
    assert r > 180 and g < 100                        # the red rectangle is in the picture
    assert list(c.clipboard.last)[:2] == [PNG, DIB]   # also on the clipboard for Ctrl+V
    assert c.overlays == []
    assert any("그림" in m and "PowerPoint에 넣었습니다" in m for m in c.messages)


def test_APP_37_powerpoint_missing_keeps_clipboard(make):
    c = make()
    c.powerpoint = FakePpt(ok=False)
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].side_bar.trigger("ppt")
    assert c.clipboard.payloads
    assert any("설치" in m and "Ctrl+V" in m for m in c.messages)


def test_APP_63_ppt_in_text_mode_sends_text_and_keeps_text_on_clipboard(make):
    from capture_tool.platform.powerpoint import TextItem
    lines = [OcrLine("견적 요약", (10, 10, 100, 20), 0.99), OcrLine("담당 010-1234-5678", (10, 40, 180, 20), 0.98)]
    c, ov = _editing(make, ocr=FakeOcr(lines))
    c.powerpoint = FakePpt()
    ov.side_bar.trigger("text")
    QTest.keyClick(ov, Qt.Key_C, Qt.ControlModifier)          # the user's Ctrl+C in text mode
    ov.side_bar.trigger("ppt")
    item = c.powerpoint.items[0]
    assert isinstance(item, TextItem)
    assert item.text.startswith("견적 요약\n담당") and "010-1234-5678" not in item.text   # same as copied
    assert UNICODE in c.clipboard.last and "견적 요약" in c.clipboard.last[UNICODE]      # Ctrl+V still text
    assert GVML not in c.clipboard.last and PNG not in c.clipboard.last
    assert any("글자" in m and "PowerPoint에 넣었습니다" in m for m in c.messages)


def test_APP_64_ppt_in_text_mode_after_partial_drag_sends_that_part(make):
    from capture_tool.platform.powerpoint import TextItem
    lines = [OcrLine("0123456789", (100, 10, 200, 20), 0.95)]
    c, ov = _editing(make, ocr=FakeOcr(lines))
    c.powerpoint = FakePpt()
    ov.side_bar.trigger("text")
    drag(ov, (100 + 140, 100 + 5), (100 + 200, 100 + 35))    # copies "234"
    ov.side_bar.trigger("ppt")
    assert isinstance(c.powerpoint.items[0], TextItem) and c.powerpoint.items[0].text == "234"


def test_APP_65_frozen_powerpoint_is_reported_and_nothing_hangs(make):
    from capture_tool.platform.powerpoint import PowerPointTimeout
    c, ov = _editing(make)
    c.powerpoint = FakePpt(error=PowerPointTimeout("PowerPoint가 응답하지 않습니다."))
    ov.side_bar.trigger("ppt")
    assert c.overlays == []                                   # capture finished, UI free
    assert PNG in c.clipboard.last                            # the picture is still on the clipboard
    assert any("응답하지 않" in m and "Ctrl+V" in m for m in c.messages)


def test_APP_66_second_click_while_sending_is_ignored(make):
    c, ov = _editing(make)
    ppt = FakePpt()
    ppt.busy = True
    c.powerpoint = ppt
    ov.side_bar.trigger("ppt")
    assert ppt.calls == 0
    assert PNG in c.clipboard.last
    assert any("보내는 중" in m for m in c.messages)


def test_APP_67_nothing_inserted_is_reported(make):
    c, ov = _editing(make)
    c.powerpoint = FakePpt(added=0)
    ov.side_bar.trigger("ppt")
    assert any("Ctrl+V" in m for m in c.messages)


def test_APP_68_shapes_button_without_shapes_falls_back_to_picture(make):
    from capture_tool.platform.powerpoint import Picture
    c, ov = _editing(make)
    c.powerpoint = FakePpt()
    ov.side_bar.trigger("ppt_shapes")
    assert isinstance(c.powerpoint.items[0], Picture)
    assert any("도형이 없어" in m for m in c.messages)


def test_APP_69_font_box_lists_popular_korean_fonts_first(make):
    from PySide6.QtGui import QFontDatabase
    for f in ("malgun.ttf", "batang.ttc", "gulim.ttc", "arial.ttf"):
        QFontDatabase.addApplicationFont(rf"C:\Windows\Fonts\{f}")
    c, ov = _editing(make)
    ov.set_tool("text")
    box = ov.toolbar.buttons["font_family"]
    labels = [box.itemText(i) for i in range(box.count())]
    assert labels[0] == "맑은 고딕"
    sep = next(i for i in range(box.count()) if box.itemText(i) == "" and box.itemData(i) is None)
    assert all(box.itemData(i) for i in range(sep))                    # favorites before the separator
    assert "Arial" in labels[sep + 1:]
    ov.toolbar.set_font_family("Arial")
    assert box.currentText() == "Arial"
    box.setCurrentIndex(0)                                             # the user picks 맑은 고딕
    assert ov.toolbar.font_family == box.itemData(0)


def test_APP_44_drm_pc_explains_office_ai_error_once(make):
    c = make()
    c.powerpoint = FakePpt()
    c.drm = "Fasoo DRM"
    for _ in range(2):
        c.start_capture()
        drag(c.overlays[0], (100, 100), (400, 300))
        c.overlays[0].side_bar.trigger("ppt")
    notes = [m for m in c.messages if "Fasoo DRM" in m]
    assert len(notes) == 1
    assert "ai.exe" in notes[0] and "OK" in notes[0]
    assert c.settings.drm_notice_shown is True
    assert c.powerpoint.calls == 2          # still pastes; the Office dialog is harmless


def test_APP_45_no_drm_no_notice(make):
    c = make()
    c.powerpoint = FakePpt()
    c.drm = None
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].side_bar.trigger("ppt")
    assert not any("DRM" in m for m in c.messages)


# --- v0.3: thickness, text style, drag-to-copy text, spreadsheet tables, same size in PPT ---

def _editing(make, **kw):
    c = make(**kw)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    return c, ov


def test_APP_46_custom_thickness_and_bracket_keys(make):
    c, ov = _editing(make)
    ov.toolbar.set_width(13)
    ov.set_tool("rect")
    drag(ov, (150, 150), (250, 250))
    assert c.session.document.shapes[-1].width == 13
    QTest.keyClick(ov, Qt.Key_BracketRight)
    assert ov.toolbar.line_width == 14
    QTest.keyClick(ov, Qt.Key_BracketLeft, Qt.ShiftModifier)
    assert ov.toolbar.line_width == 9
    ov.toolbar.palette.width_spin.setValue(27)
    assert ov.toolbar.line_width == 27


def test_APP_47_restyle_selected_shape_and_undo(make):
    c, ov = _editing(make)
    ov.set_tool("rect")
    drag(ov, (150, 150), (250, 250))
    ov.set_tool("select")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(150, 200))   # click its edge
    assert ov.selected == 0
    ov.set_color("#1971C2")
    ov.toolbar.set_width(9)
    s = c.session.document.shapes[0]
    assert (s.color, s.width) == ("#1971C2", 9)
    c.session.document.undo()
    c.session.document.undo()
    assert c.session.document.shapes[0].color == "#E03131"


def test_APP_48_text_style_shortcuts(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    ed = ov._editor
    ed.insert("강조")   # like an IME commit (QTest.keyClicks can't type Hangul)
    for key in (Qt.Key_B, Qt.Key_I, Qt.Key_U, Qt.Key_5):
        QTest.keyClick(ed, key, Qt.ControlModifier)
    for _ in range(3):
        QTest.keyClick(ed, Qt.Key_BracketRight, Qt.ControlModifier)
    assert ed.font().bold() and ed.font().italic() and ed.font().underline() and ed.font().strikeOut()
    QTest.keyClick(ed, Qt.Key_Return)
    assert c.overlays == [ov]                 # Enter finished the text, not the whole capture
    s = c.session.document.shapes[-1]
    assert (s.text, s.bold, s.italic, s.underline, s.strike) == ("강조", True, True, True, True)
    assert s.font_size == ov.toolbar.default_font_size + 6
    tb = ov.toolbar
    assert tb.buttons["bold"].isChecked() and tb.buttons["strike"].isChecked()


def test_APP_48b_escape_in_text_input_cancels_only_the_text(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    ov._editor.insert("지울 글자")
    QTest.keyClick(ov._editor, Qt.Key_Escape)
    assert c.overlays == [ov] and c.session.document.shapes == []


def _open_editors(ov):
    from capture_tool.app.overlay import TextEditor
    return [e for e in ov.findChildren(TextEditor) if e.isVisible()]


def test_APP_55_click_elsewhere_removes_empty_text_box(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    assert len(_open_editors(ov)) == 1
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(350, 300))   # nothing typed
    assert _open_editors(ov) == []                                         # it disappears...
    assert c.session.document.shapes == []                                 # ...and adds nothing


def test_APP_56_click_elsewhere_commits_typed_text(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    ov._editor.insert("메모")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(350, 300))
    assert _open_editors(ov) == []
    assert [s.text for s in c.session.document.shapes] == ["메모"]


def test_APP_57_never_more_than_one_text_box(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    for i in range(6):
        QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(150 + i * 40, 150 + i * 30))
        assert len(_open_editors(ov)) <= 1
    assert c.session.document.shapes == []


def test_APP_58_switching_tool_closes_text_box(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    ov._editor.insert("남김")
    ov.set_tool("rect")
    assert _open_editors(ov) == [] and [s.text for s in c.session.document.shapes] == ["남김"]


def test_APP_59_copy_while_typing_keeps_the_text(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    ov._editor.insert("포함")
    ov.side_bar.trigger("copy")
    assert c.last_document.shapes[-1].text == "포함"
    assert c.clipboard.last  # and the image (with the text) was copied


def _some_other_font():
    """A real font other than the default (headless Qt only knows fonts we load)."""
    from PySide6.QtGui import QFontDatabase
    fid = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\arial.ttf")
    return QFontDatabase.applicationFontFamilies(fid)[0]


def test_APP_60_choose_font_for_new_text(make):
    c, ov = _editing(make)
    ov.set_tool("text")
    combo = ov.toolbar.buttons["font_family"]
    assert combo.isVisible() and combo.currentText()
    fam = _some_other_font()
    ov.toolbar.set_font_family(fam)
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(200, 200))
    assert ov._editor.font().family() == fam          # preview while typing
    ov._editor.insert("글씨체")
    QTest.keyClick(ov._editor, Qt.Key_Return)
    assert c.session.document.shapes[-1].font_family == fam


def test_APP_61_change_font_of_selected_text_and_undo(make):
    from capture_tool.core.annotations import Shape
    c, ov = _editing(make)
    c.session.document.add(Shape(kind="text", points=[(60, 60)], text="메모", color="#000000"))
    ov.set_tool("select")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(165, 170))
    fam = _some_other_font()
    ov.toolbar.set_font_family(fam)
    assert c.session.document.shapes[0].font_family == fam
    c.session.document.undo()
    assert c.session.document.shapes[0].font_family == "Malgun Gothic"


def test_APP_62_font_remembered_for_next_capture(make):
    c, ov = _editing(make)
    fam = _some_other_font()
    ov.toolbar.set_font_family(fam)
    QTest.keyClick(ov, Qt.Key_Return)                  # finish -> remembers style
    assert c.settings.last_font_family == fam
    c.start_capture()
    assert c.overlays[0].toolbar.font_family == fam


def test_APP_49_text_style_on_selected_text_and_delete_key(make):
    c, ov = _editing(make)
    c.session.document.add(__import__("capture_tool.core.annotations", fromlist=["Shape"]).Shape(
        kind="text", points=[(60, 60)], text="메모", color="#000000"))
    ov.set_tool("select")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(165, 170))
    assert ov.selected == 0
    QTest.keyClick(ov, Qt.Key_B, Qt.ControlModifier)
    QTest.keyClick(ov, Qt.Key_BracketRight, Qt.ControlModifier)
    s = c.session.document.shapes[0]
    assert s.bold and s.font_size > 20
    QTest.keyClick(ov, Qt.Key_Delete)
    assert c.session.document.shapes == []


def test_APP_50_drag_over_text_copies_just_that_part(make):
    lines = [OcrLine("0123456789", (100, 10, 200, 20), 0.95), OcrLine("다음 줄", (100, 60, 80, 20), 0.95)]
    c, ov = _editing(make, ocr=FakeOcr(lines))
    ov.side_bar.trigger("text")
    assert "0123456789" in c.clipboard.last[UNICODE]          # everything is copied first
    # selection starts at (100,100); drag over characters 2..4 of the first line
    drag(ov, (100 + 140, 100 + 5), (100 + 200, 100 + 35))
    assert c.clipboard.last[UNICODE] == "234"
    assert any("3자" in m for m in c.messages)
    QTest.keyClick(ov, Qt.Key_Escape)                           # leave text mode, keep the capture
    assert ov.ocr_lines is None and c.overlays == [ov]
    QTest.keyClick(ov, Qt.Key_Escape)
    assert c.overlays == []


def test_APP_51_text_window_closes_with_escape(make):
    lines = [OcrLine("가나다", (10, 10, 60, 20), 0.95)]
    c, ov = _editing(make, ocr=FakeOcr(lines))
    ov.side_bar.trigger("text")
    ov.ocr_bar.trigger("window")
    panel = c.text_panel
    assert panel.isVisible() and panel.close_button.isVisible()
    QTest.keyClick(panel, Qt.Key_Escape)
    assert not panel.isVisible()


def test_APP_52_spreadsheet_capture_copies_as_table(make):
    from tests.test_table import excel_like
    img, _ = excel_like(rows=3, cols=3, cw=120, rh=28, x0=10, y0=10)
    screen_img = np.full((600, 800, 3), 255, np.uint8)
    screen_img[100:100 + img.shape[0], 100:100 + img.shape[1]] = img
    items = [("품목", (20, 15, 40, 18)), ("수량", (140, 15, 40, 18)), ("금액", (260, 15, 40, 18)),
             ("사과", (20, 43, 40, 18)), ("3", (140, 43, 10, 18)), ("9,000", (260, 43, 50, 18)),
             ("배", (20, 71, 20, 18)), ("1,000", (260, 71, 50, 18))]
    lines = [OcrLine(t, b, 0.95) for t, b in items]
    c = make(screen=FakeScreen(image=screen_img), ocr=FakeOcr(lines))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (100 + img.shape[1], 100 + img.shape[0]))
    ov.side_bar.trigger("text")
    p = c.clipboard.last
    assert p[UNICODE] == "품목\t수량\t금액\r\n사과\t3\t9,000\r\n배\t\t1,000"
    assert b"<table>" in p["HTML Format"]
    assert any("표" in m and "3행" in m for m in c.messages)


def test_APP_53_same_size_in_powerpoint_on_150_percent_screen(make):
    big = Monitor(0, Rect(0, 0, 1200, 900), 1.5, True, "HiDPI")
    c = make(screen=FakeScreen(monitors=[big]))
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))            # logical px on a 1.5 screen
    ov.set_tool("rect")
    drag(ov, (150, 150), (250, 250))            # 100 logical = 150 physical px
    ov.toolbar.trigger("shapes")
    xml = zipfile.ZipFile(io.BytesIO(c.clipboard.last[GVML])).read("clipboard/drawings/drawing1.xml").decode()
    from capture_tool.core.drawingml import px_to_emu
    assert f'cx="{px_to_emu(100)}"' in xml      # same size as seen on screen


def test_APP_54_picture_carries_screen_dpi(make):
    big = Monitor(0, Rect(0, 0, 1200, 900), 1.5, True, "HiDPI")
    c = make(screen=FakeScreen(monitors=[big]))
    c.start_capture()
    drag(c.overlays[0], (100, 100), (300, 200))
    QTest.keyClick(c.overlays[0], Qt.Key_Return)
    png = c.clipboard.last[PNG]
    assert b"pHYs" in png


def test_APP_30_fullscreen_mode_copies_cursor_monitor(make):
    c = make(FakeScreen(cursor=(900, 10), monitors=[MON_A, MON_B]))
    c.start_capture(mode="fullscreen")
    img = decode_png(c.clipboard.last[PNG])
    assert img.shape[:2] == (600, 800)
    assert c.overlays == []
