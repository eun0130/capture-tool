"""The window after a recording: watch it, cut off the start / end with the two handles, choose MP4
(with sound) or GIF (no sound, for messengers), see the size, then copy it as a file, save it, save it
somewhere else, open the folder or record again. Exports run on a thread (the OS writer is opened
there) and never block the window."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..core.recording_export import export, gif_size_estimate, mp4_size_estimate, video_info
from .recording_ui import mmss, size_text
from .render import bgr_to_pixmap

log = logging.getLogger("capture_tool")

HANDLE = 7                                    # px around a handle that grabs it
GIF_MAX_SECONDS = 60                          # a GIF holds every picture in memory: a minute at most
GIF_CHOICES = (("GIF 보통 (10fps · 폭 800)", 10, 800), ("GIF 작게 (8fps · 폭 640)", 8, 640),
               ("GIF 선명하게 (15fps · 폭 1024)", 15, 1024))


class Timeline(QWidget):
    """Thumbnails of the recording; two blue handles keep [start, end); a red line is the play head."""
    changed = Signal(float, float)
    seeked = Signal(float)

    def __init__(self, duration: float, thumbs: list[QPixmap] | None = None):
        super().__init__()
        self.duration = max(0.01, duration)
        self.thumbs = thumbs or []
        self.start, self.end, self.pos = 0.0, self.duration, 0.0
        self._drag: str | None = None
        self.setMinimumHeight(52)
        self.setMouseTracking(True)

    def x_of(self, t: float) -> float:
        return HANDLE + (self.width() - 2 * HANDLE) * t / self.duration

    def t_of(self, x: float) -> float:
        return min(self.duration, max(0.0, (x - HANDLE) / max(1, self.width() - 2 * HANDLE) * self.duration))

    def set_range(self, start: float, end: float) -> None:
        start = min(max(0.0, start), self.duration)
        end = min(max(0.0, end), self.duration)
        if end - start < 0.1:                       # keep at least a tenth of a second
            return
        self.start, self.end = start, end
        self.pos = min(max(self.pos, start), end)
        self.update()
        self.changed.emit(start, end)

    def set_pos(self, t: float) -> None:
        self.pos = t
        self.update()

    def mousePressEvent(self, e):
        x = e.position().x()
        if abs(x - self.x_of(self.start)) <= HANDLE:
            self._drag = "start"
        elif abs(x - self.x_of(self.end)) <= HANDLE:
            self._drag = "end"
        else:
            self._drag = None
            t = min(max(self.t_of(x), self.start), self.end)
            self.set_pos(t)
            self.seeked.emit(t)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag == "start":
            self.set_range(min(self.t_of(x), self.end - 0.1), self.end)
        elif self._drag == "end":
            self.set_range(self.start, max(self.t_of(x), self.start + 0.1))
        else:
            near = min(abs(x - self.x_of(self.start)), abs(x - self.x_of(self.end))) <= HANDLE
            self.setCursor(Qt.SizeHorCursor if near else Qt.ArrowCursor)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect().adjusted(HANDLE, 4, -HANDLE, -4)
        p.fillRect(r, QColor("#2B2F3A"))
        if self.thumbs:
            w = r.width() / len(self.thumbs)
            for i, pm in enumerate(self.thumbs):
                p.drawPixmap(QRect(int(r.left() + i * w), r.top(), int(w) + 1, r.height()), pm)
        x0, x1 = self.x_of(self.start), self.x_of(self.end)
        shade = QColor(0, 0, 0, 150)
        p.fillRect(QRect(r.left(), r.top(), int(x0 - r.left()), r.height()), shade)
        p.fillRect(QRect(int(x1), r.top(), int(r.right() - x1) + 1, r.height()), shade)
        p.setPen(QPen(QColor("#1C5FD4"), 3))
        p.drawRect(QRect(int(x0), r.top(), int(x1 - x0), r.height()))
        p.setBrush(QColor("#1C5FD4"))
        for x in (x0, x1):
            p.drawRoundedRect(QRect(int(x) - 4, 0, 8, self.height()), 3, 3)
        p.setPen(QPen(QColor("#E03131"), 2))
        xp = int(self.x_of(self.pos))
        p.drawLine(xp, 0, xp, self.height())


class _Done(QObject):
    sig = Signal(object, object)            # (what, Path | Exception)


class RecordingResult(QWidget):
    """deps: open_writer(**kw), set_clipboard(payload) -> bool, save_folder() -> Path, unique(folder,
    ext) -> Path, ask_path(default, filter) -> Path | None, open_folder(path), notify(msg),
    again(), share_dir() -> Path, files_payload(paths) -> dict."""

    def __init__(self, path: Path, wav: Path | None, deps: dict, fmt: str = "mp4", sync: bool = False,
                 note: str = ""):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.path, self.wav, self.deps, self.sync = Path(path), wav, deps, sync
        self.w, self.h, self.fps, self.duration = video_info(self.path)
        self.sound = wav is not None and Path(wav).exists()
        self.busy = False
        self.last_saved: Path | None = None
        self._done = _Done()
        self._done.sig.connect(self._finished, Qt.QueuedConnection)
        self.setWindowTitle(f"녹화 결과 — {mmss(self.duration)} · {self.w}×{self.h}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        self.note_label = QLabel(note)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #B35C00;")
        self.note_label.setVisible(bool(note))
        v.addWidget(self.note_label)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(480, 270)
        self.preview.setStyleSheet("background: #1C1F26; border-radius: 8px;")
        v.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.play_button = QPushButton("▶ 재생")
        self.play_button.clicked.connect(self.toggle_play)
        row.addWidget(self.play_button)
        self.time_label = QLabel("")
        row.addWidget(self.time_label)
        row.addStretch(1)
        row.addWidget(QLabel("파란 손잡이를 끌어 앞뒤를 잘라 냅니다"))
        v.addLayout(row)
        self.timeline = Timeline(self.duration, self._thumbs())
        self.timeline.changed.connect(self._range_changed)
        self.timeline.seeked.connect(self.show_at)
        v.addWidget(self.timeline)
        row = QHBoxLayout()
        row.addWidget(QLabel("형식"))
        self.fmt_group = QButtonGroup(self)
        self.mp4_button = QPushButton("MP4 동영상" + ("" if self.sound else " (소리 없음)"))
        self.gif_button = QPushButton("GIF 움짤 (소리 없음)")
        for i, b in enumerate((self.mp4_button, self.gif_button)):
            b.setCheckable(True)
            self.fmt_group.addButton(b, i)
            row.addWidget(b)
        (self.gif_button if fmt == "gif" else self.mp4_button).setChecked(True)
        self.gif_quality = QComboBox()
        for label, _, _ in GIF_CHOICES:
            self.gif_quality.addItem(label)
        self.gif_quality.currentIndexChanged.connect(lambda _i: self._update_size())
        row.addWidget(self.gif_quality)
        self.fmt_group.idToggled.connect(lambda _i, _on: self._update_size())
        row.addStretch(1)
        self.size_label = QLabel("")
        row.addWidget(self.size_label)
        v.addLayout(row)
        row = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for name, label in (("copy", "복사"), ("save", "저장"), ("save_as", "다른 이름 저장"),
                            ("open_folder", "저장 폴더")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name: self.trigger(n))
            row.addWidget(b)
            self.buttons[name] = b
        self.buttons["copy"].setDefault(True)
        row.addStretch(1)
        for name, label in (("again", "다시 녹화"), ("close", "닫기")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name: self.trigger(n))
            row.addWidget(b)
            self.buttons[name] = b
        v.addLayout(row)
        self.status = QLabel("")
        v.addWidget(self.status)
        self._cap = None
        self._last = None
        self._play = QTimer(self)
        self._play.timeout.connect(self._next_frame)
        self._update_size()
        self.show_at(0.0)
        self.resize(760, 600)

    # --- picture -------------------------------------------------------------------------------------
    def _thumbs(self, n: int = 12) -> list[QPixmap]:
        import cv2
        cap, out = cv2.VideoCapture(str(self.path)), []
        try:
            for i in range(n):
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * self.duration * (i + 0.5) / n)
                ok, img = cap.read()
                if ok:
                    small = cv2.resize(img, (96, max(1, round(96 * img.shape[0] / img.shape[1]))))
                    out.append(bgr_to_pixmap(np.ascontiguousarray(small)))
        finally:
            cap.release()
        return out

    def _show(self, img) -> None:
        """The frame fitted into the preview, sharp on a Retina / high-DPI screen."""
        self._last = img
        dpr = self.preview.devicePixelRatioF() or 1.0
        size = self.preview.size()
        pm = bgr_to_pixmap(np.ascontiguousarray(img)).scaled(
            max(1, int((size.width() - 8) * dpr)), max(1, int((size.height() - 8) * dpr)), Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pm)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_last", None) is not None:
            self._show(self._last)

    def show_at(self, t: float) -> None:
        import cv2
        self.stop_play()
        cap = cv2.VideoCapture(str(self.path))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * t)
            ok, img = cap.read()
        finally:
            cap.release()
        if ok:
            self._show(img)
        self.timeline.set_pos(t)
        self._time(t)

    def _time(self, t: float) -> None:
        self.time_label.setText(f"{mmss(t)} / {mmss(self.duration)}")

    def toggle_play(self) -> None:
        if self._play.isActive():
            self.stop_play()
            return
        import cv2
        tl = self.timeline
        start = tl.pos if tl.start <= tl.pos < tl.end - 0.05 else tl.start
        self._cap = cv2.VideoCapture(str(self.path))
        self._cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * start)
        self.play_button.setText("❚❚ 멈춤")
        self._play.start(max(15, int(1000 / (self.fps or 15))))

    def stop_play(self) -> None:
        self._play.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.play_button.setText("▶ 재생")

    def _next_frame(self) -> None:
        import cv2
        ok, img = self._cap.read() if self._cap is not None else (False, None)
        t = self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 if ok else self.timeline.end
        if not ok or t >= self.timeline.end:
            self.stop_play()
            return
        self._show(img)
        self.timeline.set_pos(t)
        self._time(t)

    # --- choices -------------------------------------------------------------------------------------
    @property
    def kind(self) -> str:
        return "gif" if self.gif_button.isChecked() else "mp4"

    def _range_changed(self, start: float, _end: float) -> None:
        self._update_size()
        self.show_at(start)

    def gif_settings(self) -> tuple[int, int]:
        _, fps, width = GIF_CHOICES[max(0, self.gif_quality.currentIndex())]
        return fps, width

    def estimate(self) -> int:
        secs = self.timeline.end - self.timeline.start
        if self.kind == "gif":
            fps, width = self.gif_settings()
            w = min(self.w, width)
            return gif_size_estimate(w, round(self.h * w / max(1, self.w)), secs, fps)
        if self.timeline.start <= 0.05 and self.timeline.end >= self.duration - 0.05:
            return self.path.stat().st_size
        return mp4_size_estimate(self.w, self.h, secs, int(round(self.fps)), self.sound)

    def _update_size(self) -> None:
        self.gif_quality.setVisible(self.kind == "gif")
        tl = self.timeline
        secs = tl.end - tl.start
        cut = "" if tl.start <= 0.05 and tl.end >= self.duration - 0.05 else f"{tl.start:.1f}~{tl.end:.1f}초 → "
        self.size_label.setText(f"{cut}{secs:.0f}초 · 약 {size_text(self.estimate())}")

    # --- actions -------------------------------------------------------------------------------------
    def trigger(self, name: str) -> None:
        d = self.deps
        if name == "close":
            self.close()
        elif name == "again":
            self.close()
            d["again"]()
        elif name == "open_folder":
            d["open_folder"](self.last_saved.parent if self.last_saved else d["save_folder"]())
        elif name in ("copy", "save", "save_as"):
            self.export_to(name)

    def _target(self, what: str) -> Path | None:
        ext = "." + self.kind
        d = self.deps
        if what == "copy":
            return d["unique"](d["share_dir"](), ext)
        if what == "save":
            return d["unique"](d["save_folder"](), ext)
        filt = "GIF 움짤 (*.gif)" if self.kind == "gif" else "MP4 동영상 (*.mp4)"
        chosen = d["ask_path"](d["unique"](d["save_folder"](), ext), filt)
        if chosen is None:
            return None
        return chosen if chosen.suffix.lower() == ext else chosen.with_suffix(ext)

    def export_to(self, what: str) -> None:
        if self.busy:
            return
        start, end, kind = self.timeline.start, self.timeline.end, self.kind
        if kind == "gif" and end - start > GIF_MAX_SECONDS + 0.05:      # (before asking where to save)
            self.status.setText(f"GIF는 {GIF_MAX_SECONDS // 60}분까지만 만듭니다. 파란 손잡이로 줄이거나 MP4로 저장하세요.")
            return
        dst = self._target(what)
        if dst is None:
            return
        fps, width = self.gif_settings()
        writer = self.deps["open_writer"]

        def work():
            return export(self.path, self.wav, start, end, kind, dst, writer, gif_fps=fps, max_width=width)
        self.busy = True
        for b in self.buttons.values():
            b.setEnabled(False)
        self.status.setText("GIF 만드는 중…" if kind == "gif" else "동영상 만드는 중…")
        if self.sync:
            try:
                out = work()
            except Exception as e:  # noqa: BLE001
                out = e
            self._finished(what, out)
            return

        def run():
            try:
                out = work()
            except Exception as e:  # noqa: BLE001 - shown in the window
                log.exception("recording export failed")
                out = e
            self._done.sig.emit(what, out)
        threading.Thread(target=run, daemon=True, name="recording-export").start()

    def _finished(self, what: str, out) -> None:
        self.busy = False
        for b in self.buttons.values():
            b.setEnabled(True)
        d = self.deps
        if isinstance(out, Exception):
            self.status.setText(f"만들지 못했습니다: {out}")
            d["notify"](f"녹화 파일을 만들지 못했습니다: {out}")
            return
        size = size_text(out.stat().st_size) if out.exists() else ""
        if what == "copy":
            ok = d["set_clipboard"](d["files_payload"]([out]))
            from .. import platform as pf
            key = "Cmd+V" if pf.is_mac() else "Ctrl+V"
            msg = (f"녹화 파일({size})을 복사했습니다. 메신저·메일 창에 {key} 하세요." if ok
                   else "클립보드에 넣지 못했습니다. 저장한 뒤 파일을 끌어다 놓으세요.")
        else:
            self.last_saved = out
            msg = f"저장했습니다 ({size}): {out}"
        self.status.setText(msg)
        d["notify"](msg)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.stop_play()
        super().closeEvent(e)
