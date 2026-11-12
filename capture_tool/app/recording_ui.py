"""Screen recording on screen: the 3-2-1 count, the red border around the area, the control bar
(time, size so far, microphone, pause, stop) and `Recorder`, which runs a `RecordingSession` on its
own thread and hands it back when it ends.

The border is drawn just outside the area and the bar sits outside it too (inside only when there is
no room, and then it is kept out of the picture), so nothing of ours ends up in the video. The
recording thread opens the OS writer itself (Media Foundation wants COM on the thread that uses it)."""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from datetime import datetime
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..core.recording import MousePainter, RecordingSession, RecordOptions
from ..core.recording_export import mp4_size_estimate

log = logging.getLogger("capture_tool")

BORDER = 4                       # logical px of red outside the area
KEEP_HOURS = 24                  # temporary recordings older than this are removed


def recordings_dir() -> Path:
    """Where recordings wait until they are saved or copied (never the save folder)."""
    d = Path(tempfile.gettempdir()) / "CaptureTool-recordings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_old_recordings(folder: Path | None = None, now: float | None = None) -> int:
    """Remove temporary recordings older than a day; returns how many files went."""
    folder = folder or recordings_dir()
    now = time.time() if now is None else now
    gone = 0
    for p in folder.glob("*"):
        try:
            if p.is_file() and now - p.stat().st_mtime > KEEP_HOURS * 3600:
                p.unlink()
                gone += 1
        except OSError:
            pass
    return gone


def new_recording_path(folder: Path | None = None) -> Path:
    folder = folder or recordings_dir()
    base = "rec_" + datetime.now().strftime("%y%m%d_%H%M%S")
    p, n = folder / f"{base}.mp4", 2
    while p.exists():
        p, n = folder / f"{base}_{n}.mp4", n + 1
    return p


def mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def size_text(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, n // 1024)} KB"


_TOP = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus


class RecordFrame(QWidget):
    """The red border just outside the recorded area; clicks go through it."""

    def __init__(self, area: QRect):
        super().__init__(None, _TOP | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.area = QRect(area)
        self.paused = False
        self.setGeometry(area.adjusted(-BORDER, -BORDER, BORDER, BORDER))

    def set_paused(self, on: bool) -> None:
        self.paused = on
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        pen = QPen(QColor("#F59F00") if self.paused else QColor("#E03131"), 3, Qt.DashLine)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))


BAR_STYLE = ("QWidget#recbar { background: rgba(20,22,28,235); border-radius: 10px; }"
             "QLabel { color: #FFFFFF; font-size: 13px; }"
             "QLabel#dot { color: #FF6B6B; font-weight: bold; }"
             "QPushButton { background: #2B2F3A; color: #FFFFFF; border: 1px solid #454B5A; border-radius: 6px;"
             " padding: 4px 10px; }"
             "QPushButton:checked { background: #5C2B2B; }"
             "QPushButton#stop { background: #E03131; border: none; font-weight: bold; }")


class RecordBar(QWidget):
    """녹화 중 · 00:12 · 1.8 MB · [마이크] [일시정지] [끝내기 (Esc)]."""
    pauseToggled = Signal(bool)
    micToggled = Signal(bool)
    stopRequested = Signal()

    def __init__(self, mic: bool, system: bool, max_seconds: int):
        super().__init__(None, _TOP)
        self.setObjectName("recbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(BAR_STYLE)
        self.max_seconds = max_seconds
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 6, 6)
        lay.setSpacing(8)
        self.state = QLabel("● 녹화 중")
        self.state.setObjectName("dot")
        lay.addWidget(self.state)
        self.time = QLabel(f"00:00 / {mmss(max_seconds)}")
        lay.addWidget(self.time)
        self.size = QLabel("")
        lay.addWidget(self.size)
        self.mic_button = None
        if mic:
            b = QPushButton("🎙 마이크 켬")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip("누르면 마이크 소리만 잠시 끕니다 (컴퓨터 소리는 그대로)")
            b.toggled.connect(self._mic)
            lay.addWidget(b)
            self.mic_button = b
        if system:
            lay.addWidget(QLabel("🔊 소리"))
        self.pause_button = QPushButton("⏸ 일시정지")
        self.pause_button.setCheckable(True)
        self.pause_button.setFocusPolicy(Qt.NoFocus)
        self.pause_button.toggled.connect(self._pause)
        lay.addWidget(self.pause_button)
        self.stop_button = QPushButton("■ 끝내기 (Esc)")
        self.stop_button.setObjectName("stop")
        self.stop_button.setFocusPolicy(Qt.NoFocus)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        lay.addWidget(self.stop_button)
        self.adjustSize()

    def _mic(self, off: bool) -> None:
        self.mic_button.setText("🎙 마이크 끔" if off else "🎙 마이크 켬")
        self.micToggled.emit(not off)

    def _pause(self, on: bool) -> None:
        self.pause_button.setText("▶ 계속" if on else "⏸ 일시정지")
        self.state.setText("❚❚ 일시정지" if on else "● 녹화 중")
        self.pauseToggled.emit(on)

    def show_status(self, elapsed: float, size: int) -> None:
        self.time.setText(f"{mmss(elapsed)} / {mmss(self.max_seconds)}")
        self.size.setText(f"· {size_text(size)}" if size else "")

    def place(self, area: QRect, screen: QRect) -> bool:
        """Above the area's right end; below it; else inside its top. True when it is inside."""
        self.adjustSize()
        w, h = self.width(), self.height()
        x = min(max(screen.left(), area.right() + BORDER - w), screen.right() - w)
        for y in (area.top() - BORDER - h - 4, area.bottom() + BORDER + 4):
            if screen.top() <= y and y + h <= screen.bottom():
                self.move(QPoint(x, y))
                return False
        self.move(QPoint(x, area.top() + 8))
        return True


class Countdown(QWidget):
    """3, 2, 1 in the middle of the area, then `done`."""
    done = Signal()

    def __init__(self, area: QRect, seconds: int = 3, step_ms: int = 1000):
        super().__init__(None, _TOP | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.left, self.step_ms = seconds, step_ms
        self.resize(160, 160)
        self.move(area.center() - QPoint(80, 80))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def start(self) -> None:
        self.show()
        self._timer.start(self.step_ms)

    def _step(self) -> None:
        self.left -= 1
        if self.left <= 0:
            self._timer.stop()
            self.close()
            self.done.emit()
            return
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 22, 28, 200))
        p.drawEllipse(self.rect().adjusted(4, 4, -4, -4))
        f = p.font()
        f.setPixelSize(80)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(self.rect(), Qt.AlignCenter, str(self.left))


class Recorder(QObject):
    """One recording, from the count to the end. `ended(session)` comes on the GUI thread.

    screen: the screen service (recording_grabber, mouse_reader, open_recorder, sound_sources,
    exclude_from_capture, esc_pressed). area / screen_geo: logical px for the windows; rect: the
    physical px that are recorded."""
    ended = Signal(object)
    _finished = Signal()

    def __init__(self, screen, settings, rect, area: QRect, screen_geo: QRect, scale: float, path: Path,
                 sync: bool = False, clock=time.monotonic, sleep=time.sleep, countdown_ms: int = 1000):
        super().__init__()
        self.screen, self.settings, self.rect, self.area, self.screen_geo = screen, settings, rect, area, screen_geo
        self.scale, self.path, self.sync, self.clock, self.sleep = scale, Path(path), sync, clock, sleep
        self.countdown_ms = countdown_ms
        self.session: RecordingSession | None = None
        self.sources: list = []
        self.frame: RecordFrame | None = None
        self.bar: RecordBar | None = None
        self.countdown: Countdown | None = None
        self._stop = False
        self._thread: threading.Thread | None = None
        self._ui = QTimer(self)
        self._ui.setInterval(250)
        self._ui.timeout.connect(self._tick_ui)
        self._finished.connect(self._end, Qt.QueuedConnection)

    def _call(self, name, *args, default=None):
        fn = getattr(self.screen, name, None)
        if fn is None:
            return default
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 - an optional OS service
            log.info("recording: %s failed: %s", name, e)
            return default

    # --- start ---------------------------------------------------------------------------------
    def start(self) -> None:
        s = self.settings
        self._call("esc_pressed")                          # forget an Esc pressed before this
        if getattr(s, "record_countdown", True) and not self.sync:
            self.countdown = Countdown(self.area, 3, self.countdown_ms)
            self.countdown.done.connect(self._begin)
            self.countdown.start()
            self._call("exclude_from_capture", int(self.countdown.winId()))
            self._ui.start()                                # Esc during the count cancels it
            return
        self._begin()

    def _sound_sources(self) -> list:
        s = self.settings
        mic, system = bool(getattr(s, "record_mic", True)), bool(getattr(s, "record_system", True))
        if not (mic or system):
            return []
        return list(self._call("sound_sources", mic, system, default=[]) or [])

    def _begin(self) -> None:
        self.countdown = None
        s = self.settings
        raw = self.screen.recording_grabber(self.rect)
        mouse = self._call("mouse_reader", self.rect)
        cursor, clicks = bool(getattr(s, "record_cursor", True)), bool(getattr(s, "record_clicks", True))
        painter = MousePainter(mouse, cursor, clicks, scale=self.scale) if mouse is not None else None

        def grab(r):
            img = raw(r)
            return painter(img, r) if painter is not None else img
        self.sources = self._sound_sources()
        opts = RecordOptions(fps=int(getattr(s, "record_fps", 15)), max_seconds=int(getattr(s, "record_max_minutes", 10)) * 60)
        self.session = RecordingSession(grab, partial(self.screen.open_recorder, realtime=True), self.rect, opts,
                                        self.path, self.sources)
        self.frame = RecordFrame(self.area)
        self.frame.show()
        self._call("exclude_from_capture", int(self.frame.winId()))
        names = {getattr(x, "name", "") for x in self.sources}
        self.bar = RecordBar("mic" in names, "system" in names, opts.max_seconds)
        self.bar.pauseToggled.connect(self.pause)
        self.bar.micToggled.connect(lambda on: self.session.mute("mic", not on))
        self.bar.stopRequested.connect(self.stop)
        self.bar.place(self.area, self.screen_geo)
        self.bar.show()
        self._call("exclude_from_capture", int(self.bar.winId()))
        log.info("recording %dx%d at %d fps, sound: %s", self.rect.w, self.rect.h, opts.fps, sorted(names) or "none")
        if self.sync:
            self._work()
            self._end()
            return
        self._ui.start()                                    # (again: it stopped with the count)
        self._thread = threading.Thread(target=self._work, daemon=True, name="recording")
        self._thread.start()

    # --- the recording thread ------------------------------------------------------------------
    def _work(self) -> None:
        ses = self.session
        try:
            ses.begin(self.clock())
        except Exception as e:  # noqa: BLE001 - no writer: nothing was recorded
            log.exception("recording could not start")
            ses.error, ses.state = str(e) or type(e).__name__, "failed"
            self._finished.emit()
            return
        for src in self.sources:
            try:
                src.start(lambda block, rate, src=src: ses.feed(src, block, rate))
            except Exception as e:  # noqa: BLE001 - the recording goes on without this sound
                src.error = str(e) or type(e).__name__
        try:
            ses.run(lambda: self._stop, self.clock, self.sleep)
        finally:
            for src in self.sources:
                try:
                    src.stop()
                except Exception:  # noqa: BLE001
                    pass
            if not self.sync:
                self._finished.emit()

    # --- controls ------------------------------------------------------------------------------
    def stop(self) -> None:
        self._stop = True

    def pause(self, on: bool) -> None:
        if self.session is None:
            return
        (self.session.pause if on else self.session.resume)(self.clock())
        if self.frame is not None:
            self.frame.set_paused(on)

    def cancel_countdown(self) -> None:
        if self.countdown is not None:
            self.countdown.close()
            self.countdown = None
            self.ended.emit(None)

    def _tick_ui(self) -> None:
        ses = self.session
        if ses is None:
            if self.countdown is not None and self._call("esc_pressed", default=False):
                self._ui.stop()
                self.cancel_countdown()
            return
        if self._call("esc_pressed", default=False):
            log.info("Esc: recording stopped")
            self.stop()
        if self.bar is not None:
            t = ses.elapsed
            est = mp4_size_estimate(ses.rect.w, ses.rect.h, t, ses.opts.fps, bool(self.sources))
            self.bar.show_status(t, est)

    def _end(self) -> None:
        self._ui.stop()
        for w in (self.frame, self.bar):
            if w is not None:
                w.close()
        self.frame = self.bar = None
        self.ended.emit(self.session)
