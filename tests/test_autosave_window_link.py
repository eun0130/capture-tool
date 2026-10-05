"""v0.5: automatic saving, whole-window capture (also across monitors), and links to share."""
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.clipboard_payload import HTML, PNG, UNICODE
from capture_tool.core.geometry import Monitor, Rect
from capture_tool.core.ocr import OcrLine
from capture_tool.core.settings import Settings, load, save
from capture_tool.platform.windows import WindowInfo
from tests.test_app import FakeClipboard, FakeOcr, FakePpt, FakeScreen, decode_png, drag

MON_A = Monitor(0, Rect(0, 0, 800, 600), 1.0, True, "A")
MON_B = Monitor(1, Rect(800, 0, 800, 600), 1.0, False, "B")


class TwoScreens(FakeScreen):
    """Monitor A is blue, monitor B is red; capture_window() can be faked per test."""

    def __init__(self, wins=(), window_image=None):
        super().__init__(monitors=(MON_A, MON_B), wins=wins)
        self.window_image = window_image
        self.window_calls = []

    def grab(self, r):
        self.grabs.append(r)
        img = np.zeros((r.h, r.w, 3), np.uint8)
        img[:] = (200, 60, 30) if r.x < 800 else (30, 60, 200)
        img[0, 0] = (0, 0, 0)
        return img

    def capture_window(self, hwnd, rect):
        self.window_calls.append((hwnd, rect))
        return self.window_image


@pytest.fixture
def make(qt_app, tmp_path):
    from capture_tool.app.controller import Controller
    made = []

    def _make(screen=None, ocr=None, **settings_kw):
        s = Settings(save_dir=str(tmp_path / "shots"), **settings_kw)
        c = Controller(screen=screen or FakeScreen(), clipboard=FakeClipboard(), ocr=ocr or FakeOcr(),
                       settings=s, settings_path=tmp_path / "settings.json", fallback_dir=tmp_path / "fallback",
                       sync=True)
        c.ask_save_path = lambda default, parent=None: tmp_path / "picked.png"
        made.append(c)
        return c
    yield _make
    for c in made:
        c.close_all()


def shots(tmp_path) -> list[Path]:
    d = tmp_path / "shots"
    return sorted(d.glob("*.*")) if d.exists() else []


def select(c, a=(100, 100), b=(300, 250)):
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, a, b)
    return ov


# --- auto-save ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["copy", "ppt", "pin"])
def test_AUTO_01_every_finish_saves_once_when_on(make, tmp_path, action):
    c = make(auto_save=True)
    c.powerpoint = FakePpt()
    ov = select(c)
    ov.side_bar.trigger(action)
    files = shots(tmp_path)
    assert len(files) == 1
    assert decode_png(files[0].read_bytes()).shape[:2] == (150, 200)
    assert any("저장했습니다" in m for m in c.messages)


def test_AUTO_02_save_action_saves_exactly_one_file(make, tmp_path):
    c = make(auto_save=True)
    select(c)
    c.finish("save")
    assert len(shots(tmp_path)) == 1


def test_AUTO_03_escape_without_doing_anything_saves_nothing(make, tmp_path):
    c = make(auto_save=True)
    ov = select(c)
    QTest.keyClick(ov, Qt.Key_Escape)
    assert shots(tmp_path) == []


def test_AUTO_04_text_mode_then_escape_still_saves_the_capture(make, tmp_path):
    c = make(auto_save=True, ocr=FakeOcr([OcrLine("글자", (10, 10, 60, 20), 0.9)]))
    ov = select(c)
    ov.side_bar.trigger("text")
    QTest.keyClick(ov, Qt.Key_Escape)                     # one Esc ends the capture (BUG-098)
    assert c.overlays == []
    assert len(shots(tmp_path)) == 1


def test_AUTO_05_off_saves_nothing(make, tmp_path):
    c = make(auto_save=False)
    ov = select(c)
    ov.side_bar.trigger("copy")
    assert shots(tmp_path) == []


def test_AUTO_06_fullscreen_hotkey_saves(make, tmp_path):
    c = make(auto_save=True)
    c.start_capture(mode="fullscreen")
    assert len(shots(tmp_path)) == 1


def test_AUTO_07_drawing_is_in_the_saved_file(make, tmp_path):
    c = make(auto_save=True)
    ov = select(c)
    ov.set_tool("rect")
    ov.set_color("#E03131")
    drag(ov, (150, 150), (250, 200))
    ov.side_bar.trigger("copy")
    img = decode_png(shots(tmp_path)[0].read_bytes())
    assert (img[:, :, 2] > 180).any() and (img[:, :, 1] < 90).any()


def test_AUTO_08_bad_folder_falls_back_and_says_where(make, tmp_path):
    c = make(auto_save=True)
    c.settings.save_dir = "Z:\\no\\such\\drive"
    ov = select(c)
    ov.side_bar.trigger("copy")
    assert list((tmp_path / "fallback").glob("*.png"))
    assert any("대체 폴더" in m for m in c.messages)


def test_AUTO_09_settings_label_and_round_trip(qt_app, tmp_path):
    from capture_tool.app.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings())
    assert "캡처" in dlg.auto_save.text() and "자동" in dlg.auto_save.text()
    dlg.auto_save.setChecked(True)
    assert dlg.result_settings().auto_save is True


# --- whole window (one click), also across monitors ------------------------------------------------------
WIN_IN_A = WindowInfo(21, "메모장", Rect(100, 100, 400, 300))
WIN_ACROSS = WindowInfo(22, "보고서 - Word", Rect(600, 100, 500, 300))     # 200 px on A, 300 px on B


def hover(ov, local: QPoint) -> None:
    """Mouse moving over the overlay with no button pressed (offscreen Qt doesn't synthesize it)."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    ev = QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(ov.mapToGlobal(local)), Qt.NoButton, Qt.NoButton,
                     Qt.NoModifier)
    QApplication.sendEvent(ov, ev)


def click_window(c, win, at):
    c.start_capture()
    ov = next(o for o in c.overlays if o.monitor.rect.contains(at))
    local = QPoint(at[0] - ov.monitor.rect.x, at[1] - ov.monitor.rect.y)
    hover(ov, local)
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, local)
    return ov


def test_WIN_01_click_a_window_inside_one_monitor_selects_it_for_editing(make):
    c = make(screen=TwoScreens(wins=(WIN_IN_A,)))
    ov = click_window(c, WIN_IN_A, (150, 110))            # on its title bar
    assert c.session.selection == WIN_IN_A.rect and c.overlays and ov.toolbar.isVisible()


def test_WIN_02_window_across_two_monitors_is_captured_whole(make):
    scr = TwoScreens(wins=(WIN_ACROSS,))
    c = make(screen=scr)
    click_window(c, WIN_ACROSS, (650, 110))
    img = decode_png(c.clipboard.last[PNG])
    assert img.shape[:2] == (300, 500)                   # the whole window, not just monitor A's part
    assert tuple(img[150, 50]) == (200, 60, 30)            # left part from monitor A
    assert tuple(img[150, 450]) == (30, 60, 200)           # right part from monitor B
    assert c.editor is not None and c.editor.isVisible() and c.overlays == [c.editor.canvas]
    assert "창 전체" in c.editor.windowTitle()
    assert c.editor.canvas.image.shape[:2] == (300, 500)


def test_WIN_03_window_picture_from_windows_is_preferred(make):
    pic = np.full((300, 500, 3), 77, np.uint8)
    pic[5, 5] = 0
    scr = TwoScreens(wins=(WIN_ACROSS,), window_image=pic)
    c = make(screen=scr)
    click_window(c, WIN_ACROSS, (650, 110))
    assert scr.window_calls == [(22, WIN_ACROSS.rect)]
    assert decode_png(c.clipboard.last[PNG])[150, 250].tolist() == [77, 77, 77]


def test_WIN_04_blank_window_picture_falls_back_to_the_screen(make):
    scr = TwoScreens(wins=(WIN_ACROSS,), window_image=np.zeros((300, 500, 3), np.uint8))
    c = make(screen=scr)
    click_window(c, WIN_ACROSS, (650, 110))
    img = decode_png(c.clipboard.last[PNG])
    assert tuple(img[150, 50]) == (200, 60, 30)


def test_WIN_05_part_outside_every_monitor_is_white_in_the_fallback(make):
    off = WindowInfo(23, "밖으로 나간 창", Rect(1400, 400, 400, 300))        # 200x200 visible on B
    c = make(screen=TwoScreens(wins=(off,)))
    click_window(c, off, (1450, 450))
    img = decode_png(c.clipboard.last[PNG])
    assert img.shape[:2] == (300, 400)
    assert tuple(img[50, 50]) == (30, 60, 200) and tuple(img[250, 350]) == (255, 255, 255)


def test_WIN_06_whole_window_capture_is_auto_saved(make, tmp_path):
    c = make(screen=TwoScreens(wins=(WIN_ACROSS,)), auto_save=True)
    click_window(c, WIN_ACROSS, (650, 110))
    assert len(shots(tmp_path)) == 1


def test_WIN_07_hover_label_explains_the_click(make):
    c = make(screen=TwoScreens(wins=(WIN_ACROSS, WIN_IN_A)))
    c.start_capture()
    ov = c.overlays[0]
    hover(ov, QPoint(650, 110))
    assert "창 전체" in ov.hover_label() and "모니터" in ov.hover_label()
    hover(ov, QPoint(150, 150))
    assert "창 전체" in ov.hover_label()


def test_WIN_08_first_captures_show_a_tip_then_stop(make):
    c = make()
    for i in range(4):
        c.start_capture()
        tip = c.overlays[0].tip_text()
        c.cancel()
        assert (tip != "") == (i < 3), (i, tip)
        if i == 0:
            assert "제목줄" in tip and "창 전체" in tip


def test_WIN_09_editor_actions(make, tmp_path):
    c = make(screen=TwoScreens(wins=(WIN_ACROSS,)))
    c.powerpoint = FakePpt()
    click_window(c, WIN_ACROSS, (650, 110))
    c.editor.canvas.side_bar.trigger("save_as")
    assert (tmp_path / "picked.png").exists()
    click_window(c, WIN_ACROSS, (650, 110))
    c.editor.canvas.side_bar.trigger("ppt")
    assert c.powerpoint.items
    click_window(c, WIN_ACROSS, (650, 110))
    c.editor.canvas.side_bar.trigger("pin")
    assert c.pins


# --- links ------------------------------------------------------------------------------------------------
def test_LINK_01_file_link_saves_first_and_copies_path_and_link(make, tmp_path):
    c = make(auto_save=False)
    ov = select(c)
    ov.side_bar.trigger("link_file")
    files = shots(tmp_path)
    assert len(files) == 1
    p = c.clipboard.last
    assert p[UNICODE] == str(files[0])
    html = p[HTML].decode("utf-8", "ignore")
    assert files[0].as_uri() in html and files[0].name in html
    assert any("링크" in m and "같은 PC" in m for m in c.messages)


def test_LINK_02_file_link_reuses_the_auto_saved_file(make, tmp_path):
    c = make(auto_save=True)
    ov = select(c)
    ov.side_bar.trigger("link_file")
    assert len(shots(tmp_path)) == 1


def test_LINK_03_network_folder_gives_a_network_link(make, tmp_path):
    from capture_tool.core.share import file_link
    text, url = file_link(Path(r"\\fileserver\team\캡처\Capture 1.png"))
    assert text == r"\\fileserver\team\캡처\Capture 1.png"
    assert url.startswith("file://fileserver/team/") and "%20" in url and "%EC" in url


def test_LINK_04_internet_link_asks_once_uploads_and_copies(make):
    c = make(auto_save=False)
    asked, sent = [], []
    c.ask_share_consent = lambda: asked.append(1) or True
    c.uploader = lambda png, expiry: sent.append((png[:8], expiry)) or "https://litter.catbox.moe/abc123.png"
    ov = select(c)
    ov.side_bar.trigger("link_web")
    assert sent == [(b"\x89PNG\r\n\x1a\n", "24h")] and asked == [1]
    assert c.clipboard.last[UNICODE] == "https://litter.catbox.moe/abc123.png"
    assert any("24시간" in m for m in c.messages)
    assert c.settings.share_consent is True
    ov = select(c)
    ov.side_bar.trigger("link_web")
    assert asked == [1]                                    # not asked again


def test_LINK_05_internet_link_declined_uploads_nothing(make):
    c = make()
    sent = []
    c.ask_share_consent = lambda: False
    c.uploader = lambda png, expiry: sent.append(1) or "https://x"
    ov = select(c)
    ov.side_bar.trigger("link_web")
    assert sent == [] and c.overlays                       # capture stays open


def test_LINK_06_upload_failure_is_reported(make):
    from capture_tool.core.share import ShareError
    c = make(share_consent=True)

    def fail(png, expiry):
        raise ShareError("인터넷에 연결하지 못했습니다.")
    c.uploader = fail
    before = list(c.clipboard.payloads)
    ov = select(c)
    ov.side_bar.trigger("link_web")
    assert any("링크를 만들지 못했" in m for m in c.messages)
    assert all(UNICODE not in p or not str(p[UNICODE]).startswith("http") for p in c.clipboard.payloads[len(before):])


def test_LINK_07_upload_request_shape_and_response_checks():
    from capture_tool.core.share import EXPIRIES, ShareError, upload_litterbox
    seen = {}

    def post(url, body, headers, timeout):
        seen.update(url=url, body=body, headers=headers)
        return 200, b"https://litter.catbox.moe/q1w2e3.png\n"
    url = upload_litterbox(b"\x89PNGdata", "72h", post=post)
    assert url == "https://litter.catbox.moe/q1w2e3.png"
    assert seen["url"] == "https://litterbox.catbox.moe/resources/internals/api.php"
    b = seen["body"]
    assert b'name="reqtype"' in b and b"fileupload" in b and b'name="time"' in b and b"72h" in b
    assert b'name="fileToUpload"; filename="capture.png"' in b and b"\x89PNGdata" in b
    assert "multipart/form-data; boundary=" in seen["headers"]["Content-Type"]
    assert EXPIRIES == ["1h", "12h", "24h", "72h"]
    for reply in [(200, b"<html>error</html>"), (500, b"oops"), (200, b"")]:
        with pytest.raises(ShareError):
            upload_litterbox(b"x", "24h", post=lambda *a, r=reply: r)
    with pytest.raises(ShareError):
        upload_litterbox(b"x", "24h", post=lambda *a: (_ for _ in ()).throw(OSError("timed out")))
    with pytest.raises(ValueError):
        upload_litterbox(b"x", "7d", post=post)


def test_LINK_08_settings_share_expiry(qt_app, tmp_path):
    from capture_tool.app.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings())
    assert dlg.share_expiry.currentData() == "24h"
    dlg.share_expiry.setCurrentIndex(dlg.share_expiry.findData("1h"))
    assert dlg.result_settings().share_expiry == "1h"
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"share_expiry": "7d", "share_consent": "yes"}), encoding="utf-8")
    s, warnings = load(p)
    assert s.share_expiry == "24h" and s.share_consent is False and len(warnings) == 2


def test_LINK_09_link_buttons_in_the_side_bar_explain_themselves(make):
    c = make()
    ov = select(c)
    b = ov.side_bar.buttons["link"]
    assert "링크" in b.text()
    tip = b.toolTip()
    assert "파일" in tip and "인터넷" in tip


def test_LINK_10_result_window_links(make):
    c = make(screen=TwoScreens(wins=(WIN_ACROSS,)), share_consent=True)
    c.uploader = lambda png, expiry: "https://litter.catbox.moe/zz.png"
    click_window(c, WIN_ACROSS, (650, 110))
    c.editor.canvas.side_bar.trigger("link_web")
    assert c.clipboard.last[UNICODE] == "https://litter.catbox.moe/zz.png"
    click_window(c, WIN_ACROSS, (650, 110))
    c.editor.canvas.side_bar.trigger("link_file")
    assert c.clipboard.last[UNICODE].endswith(".png")


# --- tray quick toggle ------------------------------------------------------------------------------------
def test_TRAY_01_auto_save_toggle_in_the_tray(qt_app, tmp_path, monkeypatch):
    from capture_tool.app import main
    monkeypatch.setattr(main, "data_dir", lambda: tmp_path)
    tray = main.TrayApp(qt_app, selftest=True)
    act = next(a for a in tray.menu.actions() if "자동 저장" in a.text())
    assert act.isCheckable() and act.isChecked() == tray.settings.auto_save
    act.trigger()
    assert tray.settings.auto_save is True
    s, _ = load(tmp_path / "settings.json")
    assert s.auto_save is True
    tray.controller.close_all()
