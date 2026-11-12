"""Screen recording in the app (headless Qt, fake screen / writer / clock): from the 녹화 button to the
result window, its trim handles, MP4 / GIF and copy / save."""
import numpy as np
import pytest
from PySide6.QtCore import QRect

from capture_tool.core.clipboard_payload import FILES
from capture_tool.core.settings import Settings
from tests.test_app import FakeScreen, drag, make  # noqa: F401 - the `make` fixture


class CvWriter:
    """Stands in for the OS writer: a real (mp4v) file the result window can read back."""

    def __init__(self, path, width, height, fps, audio, realtime):
        import cv2
        self.realtime, self.audio = realtime, audio
        self.w, self.h = width - width % 2, height - height % 2
        self.vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (self.w, self.h))
        self.frames = 0

    def add_frame(self, bgra, t):
        self.vw.write(np.ascontiguousarray(bgra[:self.h, :self.w, :3]))
        self.frames += 1
        return True

    def add_audio(self, pcm, t):
        return True

    def close(self):
        self.vw.release()


class RecScreen(FakeScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.writers, self.excluded, self.esc = [], [], False

    def recording_grabber(self, rect):
        def grab(r):
            img = np.full((r.h, r.w, 3), 200, np.uint8)
            img[:, :10] = 30
            return img
        return grab

    def mouse_reader(self, rect):
        return lambda: (rect.x + 20, rect.y + 20, False)

    def open_recorder(self, path, width, height, fps, audio, realtime=True):
        w = CvWriter(path, width, height, fps, audio, realtime)
        self.writers.append(w)
        return w

    def sound_sources(self, mic, system):
        return []

    def exclude_from_capture(self, hwnd):
        self.excluded.append(hwnd)
        return True

    def esc_pressed(self):
        return self.esc


def _wait(seconds, done=lambda: False):
    """Qt events with the GIL let go (QTest.qWait keeps it; the app's exec() does not)."""
    import time
    from PySide6.QtCore import QCoreApplication
    end = time.monotonic() + seconds
    while time.monotonic() < end and not done():
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _clock(step=0.05):
    t = {"now": 0.0}

    def clock():
        t["now"] += step
        return t["now"]
    return clock


@pytest.fixture
def recording(make, tmp_path):
    def _go(seconds=3, **settings):
        screen = RecScreen()
        s = Settings(save_dir=str(tmp_path / "shots"), record_max_minutes=1, record_fps=10, **settings)
        c = make(screen=screen, settings=s)
        c.recordings_dir = tmp_path / "rec"
        c.rec_clock, c.rec_sleep = _clock(), lambda _s: None
        c.start_capture("record")
        drag(c.overlays[0], (100, 100), (300, 250))
        return c, screen
    return _go


def test_RUI_01_choosing_an_area_in_record_mode_records_it_and_opens_the_result(recording):
    c, screen = recording()
    assert c.recorder is None and not any(o.isVisible() for o in c.overlays)
    w = screen.writers[0]
    assert w.realtime is True and w.audio is None and w.frames >= 590           # 1 minute (the limit) at 10 fps
    res = c.recording_result
    assert res is not None and res.w == 200 and res.h == 150 and 55 <= res.duration <= 61
    assert "최대 길이(1분)" in res.note_label.text()


def test_RUI_02_the_red_border_and_the_bar_stay_outside_the_area_and_out_of_the_picture(qt_app):
    from capture_tool.app.recording_ui import BORDER, RecordBar, RecordFrame
    area, screen = QRect(100, 200, 300, 200), QRect(0, 0, 1280, 800)
    f = RecordFrame(area)
    assert f.geometry() == area.adjusted(-BORDER, -BORDER, BORDER, BORDER)
    bar = RecordBar(mic=True, system=True, max_seconds=600)
    assert bar.place(area, screen) is False and bar.geometry().bottom() < area.top()
    assert bar.place(QRect(100, 0, 300, 200), screen) is False and bar.geometry().top() > 200   # below
    assert bar.place(QRect(0, 0, 1280, 800), screen) is True                                     # no room: inside
    bar.show_status(75, 2 * 1024 * 1024)
    assert bar.time.text() == "01:15 / 10:00" and "2.0 MB" in bar.size.text()
    seen = []
    bar.micToggled.connect(seen.append)
    bar.mic_button.click()
    assert seen == [False] and "끔" in bar.mic_button.text()
    f.close()
    bar.close()


def test_RUI_03_copy_puts_the_file_on_the_clipboard_and_save_goes_to_the_save_folder(recording, tmp_path):
    c, _ = recording()
    res = c.recording_result
    res.trigger("copy")
    payload = c.clipboard.last
    copied = payload[FILES]
    assert len(copied) == 1 and copied[0].endswith(".mp4")
    from pathlib import Path
    assert Path(copied[0]).exists() and Path(copied[0]).stat().st_size > 0
    res.trigger("save")
    saved = list((tmp_path / "shots").glob("녹화_*.mp4"))
    assert len(saved) == 1 and res.last_saved == saved[0]
    res.trigger("open_folder")
    assert c.opened[-1] == saved[0].parent


def test_RUI_04_trimmed_mp4_goes_through_the_writer_and_gif_through_pillow(recording, tmp_path):
    c, screen = recording()
    res = c.recording_result
    res.timeline.set_range(10.0, 20.0)
    assert res.size_label.text().startswith("10.0~20.0초 → 10초 · 약 ")
    res.trigger("save")
    w = screen.writers[-1]
    assert w.realtime is False and 90 <= w.frames <= 110                      # 10 s at 10 fps
    res.gif_button.click()
    res.gif_quality.setCurrentIndex(1)                                          # 작게: 8 fps
    assert res.kind == "gif" and res.gif_quality.isVisibleTo(res) and "초 · 약" in res.size_label.text()
    res.trigger("save")
    from PIL import Image
    gif = next((tmp_path / "shots").glob("*.gif"))
    im = Image.open(gif)
    assert im.size == (200, 150) and im.info.get("loop") == 0


def test_RUI_05_save_as_asks_where_and_keeps_the_extension(recording, tmp_path):
    c, _ = recording()
    res = c.recording_result
    asked = []
    c.recording_result.deps["ask_path"] = lambda default, filt: (asked.append(filt), tmp_path / "내 녹화")[1]
    res.trigger("save_as")
    assert "MP4" in asked[0] and (tmp_path / "내 녹화.mp4").exists()
    c.recording_result.deps["ask_path"] = lambda default, filt: None              # cancelled: nothing
    res.trigger("save_as")


def test_RUI_06_esc_ends_the_recording(make, tmp_path, qt_app):
    """The esc watcher runs on the UI timer (a real clock here)."""
    from capture_tool.app.recording_ui import Recorder
    from capture_tool.core.geometry import Rect
    screen = RecScreen()
    rec = Recorder(screen, Settings(record_countdown=False), Rect(0, 0, 100, 80), QRect(0, 0, 100, 80),
                   QRect(0, 0, 800, 600), 1.0, tmp_path / "r.mp4")
    ended = []
    rec.ended.connect(ended.append)
    rec.start()
    _wait(0.4)
    screen.esc = True
    _wait(4.0, lambda: bool(ended))
    assert ended and ended[0].reason == "stopped" and ended[0].frames > 0


def test_RUI_07_the_work_edition_cannot_record(make, monkeypatch):
    from capture_tool import edition
    monkeypatch.setenv("CAPTURE_EDITION", "work")
    edition.reset()
    try:
        c = make(screen=RecScreen())
        c.start_capture("record")
        drag(c.overlays[0], (100, 100), (300, 250))
        assert c.recorder is None and c.recording_result is None
        assert any("회사용" in m for m in c.messages)
    finally:
        monkeypatch.delenv("CAPTURE_EDITION")
        edition.reset()


def test_RUI_08_old_temporary_recordings_are_cleaned_up(tmp_path):
    import os
    from capture_tool.app.recording_ui import clean_old_recordings, new_recording_path
    old, new = tmp_path / "old.mp4", tmp_path / "new.mp4"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    assert clean_old_recordings(tmp_path, now=1000 + 25 * 3600) == 1 and not old.exists() and new.exists()
    p = new_recording_path(tmp_path)
    assert p.parent == tmp_path and p.suffix == ".mp4" and p.name.startswith("rec_")


def test_RUI_09_the_controller_draws_the_mouse_into_the_frames(recording):
    c, screen = recording(record_cursor=True)
    import cv2
    cap = cv2.VideoCapture(str(c.recording_result.path))
    ok, img = cap.read()
    cap.release()
    assert ok and (np.abs(img[22:30, 21:24].astype(int) - 200) > 40).any()   # the pointer at (20, 20)


def test_RUI_10_the_settings_dialog_has_a_recording_section(qt_app):
    from capture_tool.app.settings_dialog import SettingsDialog
    d = SettingsDialog(Settings())
    assert d.has_record_section and "record" in d.edits and d.edits["record"].text() in ("Ctrl + Alt + R", "Ctrl + Option + R")
    d.rec_format.setCurrentIndex(d.rec_format.findData("gif"))
    d.rec_fps.setCurrentIndex(d.rec_fps.findData(30))
    d.rec_max.setValue(25)
    d.rec_mic.setChecked(False)
    d.rec_clicks.setChecked(False)
    s = d.result_settings()
    assert (s.record_format, s.record_fps, s.record_max_minutes) == ("gif", 30, 25)
    assert s.record_mic is False and s.record_system is True and s.record_clicks is False and s.record_countdown


def test_RUI_11_the_work_settings_have_no_recording(qt_app, monkeypatch):
    from capture_tool import edition
    from capture_tool.app.settings_dialog import SettingsDialog
    monkeypatch.setenv("CAPTURE_EDITION", "work")
    edition.reset()
    try:
        d = SettingsDialog(Settings(record_fps=10))
        assert not d.has_record_section and "record" not in d.edits
        assert d.result_settings().record_fps == 10
    finally:
        monkeypatch.delenv("CAPTURE_EDITION")
        edition.reset()
