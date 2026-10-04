"""Reusing pictures without capturing again:
(1) a strip of the newest saved captures when a capture starts - one click opens it with every
    capture button; (2) any image file - dropped on the strip / the edit window / the program's
    shortcut, sent with right-click > 보내기, or opened from the tray - opens the same way."""
import os
import time

import cv2
import numpy as np
import pytest

from tests.test_app import drag, make  # noqa: F401 (fixture)


def _save_images(folder, n, start=0):
    paths = []
    for k in range(n):
        p = folder / f"2610{k + start:02d}_120000.png"
        img = np.full((40 + k, 60, 3), 30 * (k % 8), np.uint8)
        cv2.imwrite(str(p), img)
        t = time.time() - 1000 + k
        os.utime(p, (t, t))
        paths.append(p)
    return paths


@pytest.fixture
def saved(make, tmp_path):
    folder = tmp_path / "shots"
    folder.mkdir(exist_ok=True)
    c = make()
    c.settings.save_dir = str(folder)
    return c, folder


def test_REUSE_01_newest_saved_captures_first(saved):
    c, folder = saved
    paths = _save_images(folder, 11)
    (folder / "notes.txt").write_text("not a picture")
    (folder / "broken.png").write_bytes(b"not a png")
    os.utime(folder / "broken.png", (time.time() - 5000, time.time() - 5000))
    got = c.recent_captures()
    assert got == list(reversed(paths))[:8]


def test_REUSE_02_strip_shows_when_a_capture_starts(saved):
    c, folder = saved
    _save_images(folder, 3)
    c.start_capture()
    ov = c.overlays[0]
    assert ov.recent is not None and ov.recent.isVisible() and len(ov.recent.buttons) == 3


def test_REUSE_03_click_opens_it_with_every_button_without_saving_again(saved):
    c, folder = saved
    paths = _save_images(folder, 3)
    c.settings.auto_save = True
    c.start_capture()
    c.overlays[0].recent.buttons[0].click()            # the newest
    assert c.editor is not None
    assert c.editor.canvas.image.shape[:2] == cv2.imread(str(paths[-1])).shape[:2]
    assert len(list(folder.glob("*.png"))) == 3          # opened, not saved a second time
    assert "copy" in c.editor.canvas.side_bar.buttons    # the usual capture buttons are there


def test_REUSE_04_strip_hides_when_selecting_and_can_be_turned_off(saved):
    c, folder = saved
    _save_images(folder, 2)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (300, 200), (500, 400))
    assert ov.recent is None or not ov.recent.isVisible()
    c.cancel()
    c.settings.show_recent = False
    c.start_capture()
    assert c.overlays[0].recent is None or not c.overlays[0].recent.isVisible()


def test_REUSE_05_no_saved_captures_no_strip(saved):
    c, _ = saved
    c.start_capture()
    assert c.overlays[0].recent is None or not c.overlays[0].recent.isVisible()


def test_REUSE_06_open_any_image_file(make, tmp_path):
    c = make()
    p = tmp_path / "받은 사진.png"                       # Korean name
    cv2.imencode(".png", np.full((120, 200, 3), 200, np.uint8))[1].tofile(str(p))
    assert c.open_image_file(str(p))
    assert c.editor is not None and c.editor.canvas.image.shape[:2] == (120, 200)


@pytest.mark.parametrize("name,content", [("a.txt", b"hello"), ("fake.png", b"not an image"), ("missing.png", None)])
def test_REUSE_07_rejects_what_is_not_a_picture(make, tmp_path, name, content):
    c = make()
    p = tmp_path / name
    if content is not None:
        p.write_bytes(content)
    assert not c.open_image_file(str(p))
    assert c.editor is None and c.messages and "이미지" in c.messages[-1]


def test_REUSE_08_too_big_is_refused(make, tmp_path, monkeypatch):
    from capture_tool.app import controller as C
    monkeypatch.setattr(C, "MAX_OPEN_PIXELS", 1000)
    c = make()
    p = tmp_path / "big.png"
    cv2.imwrite(str(p), np.zeros((100, 100, 3), np.uint8))
    assert not c.open_image_file(str(p)) and "커서" in c.messages[-1]


def test_REUSE_09_open_replaces_the_capture_in_progress(saved, tmp_path):
    c, folder = saved
    c.start_capture()
    p = tmp_path / "x.png"
    cv2.imwrite(str(p), np.zeros((50, 80, 3), np.uint8))
    assert c.open_image_file(str(p))
    assert c.editor is not None and c.editor.canvas.image.shape[:2] == (50, 80)


def test_REUSE_10_second_launch_with_a_file_opens_it_in_the_running_app(tmp_path):
    from capture_tool.app.main import handle_instance_message, open_message
    p = tmp_path / "그림.png"
    cv2.imencode(".png", np.zeros((10, 10, 3), np.uint8))[1].tofile(str(p))
    got = []
    assert handle_instance_message(open_message(str(p)), got.append)
    assert got == ["open:" + str(p)]
    assert handle_instance_message(b"capture", got.append) and got[-1] == "capture"
    for bad in (b"open:C:/nope/none.png", b"open:" + str(tmp_path / "a.exe").encode(), b"rm -rf", b"open:" + b"x" * 5000):
        assert not handle_instance_message(bad, got.append), bad


def test_REUSE_11_send_to_menu_and_shortcut_take_files():
    from pathlib import Path
    iss = (Path(__file__).resolve().parents[1] / "installer" / "CaptureTool.iss").read_text(encoding="utf-8")
    assert "{usersendto}" in iss                           # right-click > 보내기 > 캡처 도구


def test_REUSE_12_setting_switch(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    from capture_tool.core.settings import Settings
    d = SettingsDialog(Settings())
    assert d.show_recent.isChecked()
    d.show_recent.setChecked(False)
    assert d.result_settings().show_recent is False
