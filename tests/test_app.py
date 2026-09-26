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
    assert c.text_panel is not None and c.text_panel.isVisible()


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
    def __init__(self, ok=True):
        self.calls = 0
        self.ok = ok

    def paste(self):
        from capture_tool.platform.powerpoint import PowerPointUnavailable
        self.calls += 1
        if not self.ok:
            raise PowerPointUnavailable("PowerPoint가 설치되어 있지 않습니다.")
        return 2


def test_APP_31_side_bar_next_to_selection(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (400, 300))
    sb = ov.side_bar
    assert sb.isVisible()
    g = sb.geometry()
    assert g.left() >= 400 and g.top() == 100 and g.right() <= 800
    assert list(sb.buttons) == ["copy", "save_as", "text", "ppt", "pin"]


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


def test_APP_35_send_to_powerpoint_pastes_native_shapes(make):
    lines = [OcrLine("요청 접수", (60, 60, 80, 20), 0.99), OcrLine("검토", (285, 60, 40, 20), 0.99)]
    c = make(screen=FakeScreen(image=_flow_image()), ocr=FakeOcr(lines))
    c.powerpoint = FakePpt()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (520, 260))
    c.overlays[0].side_bar.trigger("ppt")
    assert GVML in c.clipboard.last
    assert c.powerpoint.calls == 1
    assert any("PowerPoint에 붙여넣었습니다" in m for m in c.messages)


def test_APP_36_send_to_powerpoint_without_shapes_sends_image(make):
    c = make()
    c.powerpoint = FakePpt()
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].side_bar.trigger("ppt")
    assert list(c.clipboard.last)[:2] == [PNG, DIB]
    assert c.powerpoint.calls == 1
    assert any("이미지" in m for m in c.messages)


def test_APP_37_powerpoint_missing_keeps_clipboard(make):
    c = make()
    c.powerpoint = FakePpt(ok=False)
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))
    c.overlays[0].side_bar.trigger("ppt")
    assert c.clipboard.payloads
    assert any("설치" in m and "Ctrl+V" in m for m in c.messages)


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


def test_APP_30_fullscreen_mode_copies_cursor_monitor(make):
    c = make(FakeScreen(cursor=(900, 10), monitors=[MON_A, MON_B]))
    c.start_capture(mode="fullscreen")
    img = decode_png(c.clipboard.last[PNG])
    assert img.shape[:2] == (600, 800)
    assert c.overlays == []
