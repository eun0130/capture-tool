"""Put a capture into PowerPoint — the slide being viewed, or a new deck.

Safety rules (a frozen or busy PowerPoint must never freeze this app):
- only the document object model is used (AddPicture / AddTextbox / Shapes.Paste); no window
  activation, view switching or UI commands, which wait on PowerPoint's UI thread;
- every job runs in its own thread with a time limit; one job at a time."""
from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

PP_LAYOUT_BLANK = 12
MSO_TEXT_HORIZONTAL = 1
DEFAULT_TIMEOUT = 15.0
FIT = 0.9  # a big picture is shrunk to 90 % of the slide


class PowerPointUnavailable(RuntimeError):
    pass


class PowerPointTimeout(PowerPointUnavailable):
    pass


class PowerPointBusy(RuntimeError):
    pass


@dataclass
class Picture:
    image: np.ndarray          # BGR
    dpi: float = 96            # screen pixels per inch (96 × Windows scale) -> on-screen size


@dataclass
class TextItem:
    text: str
    font_family: str = "Malgun Gothic"
    font_size: float = 18      # points


@dataclass
class ClipboardShapes:
    """Native shapes already on the clipboard (Art::GVML ClipFormat)."""


@dataclass
class SendResult:
    added: int
    detail: dict = field(default_factory=dict)


def installed() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE"):
            return True
    except OSError:
        return False


def _real_app():
    import pythoncom
    import win32com.client
    try:
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except pythoncom.com_error:
        return win32com.client.Dispatch("PowerPoint.Application")


def place(w: float, h: float, slide_w: float, slide_h: float) -> tuple[float, float, float, float]:
    """(left, top, width, height) centered on the slide, shrunk to fit if needed."""
    w, h = max(w, 1.0), max(h, 1.0)
    k = min(1.0, slide_w * FIT / w, slide_h * FIT / h)
    w, h = w * k, h * k
    return (slide_w - w) / 2, (slide_h - h) / 2, w, h


def _target_slide(app, new_presentation: bool):
    app.Visible = True
    if new_presentation or app.Presentations.Count == 0:
        pres = app.Presentations.Add()
        return pres, pres.Slides.Add(1, PP_LAYOUT_BLANK)
    pres = app.ActivePresentation
    try:
        return pres, app.ActiveWindow.View.Slide       # the slide the user is looking at
    except Exception:  # noqa: BLE001 - slide sorter, slide show, no window …
        if pres.Slides.Count:
            return pres, pres.Slides(pres.Slides.Count)
        return pres, pres.Slides.Add(1, PP_LAYOUT_BLANK)


def _insert(app, item, new_presentation: bool, hook) -> SendResult:
    pres, slide = _target_slide(app, new_presentation)
    sw, sh = float(pres.PageSetup.SlideWidth), float(pres.PageSetup.SlideHeight)
    if isinstance(item, Picture):
        import cv2
        h, w = item.image.shape[:2]
        left, top, pw, ph = place(w * 72 / item.dpi, h * 72 / item.dpi, sw, sh)
        fd, path = tempfile.mkstemp(prefix="capture_", suffix=".png")
        os.close(fd)
        try:
            ok, buf = cv2.imencode(".png", item.image)
            buf.tofile(path)
            slide.Shapes.AddPicture(path, False, True, left, top, pw, ph)
        finally:
            try:
                os.remove(path)  # our own temporary file
            except OSError:
                pass
        added = 1
    elif isinstance(item, TextItem):
        lines = item.text.replace("\r\n", "\n").split("\n")
        tw = min(sw * FIT, max(200.0, max(len(l) for l in lines) * item.font_size * 1.05))
        th = min(sh * FIT, len(lines) * item.font_size * 1.6 + 10)
        left, top, tw, th = place(tw, th, sw, sh)
        box = slide.Shapes.AddTextbox(MSO_TEXT_HORIZONTAL, left, top, tw, th)
        rng = box.TextFrame.TextRange
        rng.Text = "\r".join(lines)          # PowerPoint paragraphs are separated by \r
        rng.Font.Name = item.font_family
        rng.Font.NameFarEast = item.font_family
        rng.Font.Size = item.font_size
        added = 1
    elif isinstance(item, ClipboardShapes):
        added = int(slide.Shapes.Paste().Count)
    else:
        raise TypeError(f"unknown item {item!r}")
    try:
        app.Activate()  # bring PowerPoint forward (best effort)
    except Exception:  # noqa: BLE001
        pass
    if hook is not None:
        hook(pres, slide, added)
    return SendResult(added)


def send(item, app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT,
         new_presentation: bool = False, hook: Callable | None = None) -> SendResult:
    """Insert `item`; never blocks longer than `timeout` seconds."""
    real = app_factory is None
    if real and not installed():
        raise PowerPointUnavailable("PowerPoint가 설치되어 있지 않습니다.")
    factory = app_factory or _real_app
    box: dict = {}

    def work():
        if real:
            import pythoncom
            pythoncom.CoInitialize()
        try:
            box["result"] = _insert(factory(), item, new_presentation, hook)
        except BaseException as e:  # noqa: BLE001 - reported to the caller
            box["error"] = e
        finally:
            if real:
                import pythoncom
                pythoncom.CoUninitialize()

    th = threading.Thread(target=work, name="powerpoint-send", daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise PowerPointTimeout(f"PowerPoint가 {timeout:.0f}초 동안 응답하지 않습니다.")
    err = box.get("error")
    if isinstance(err, PowerPointUnavailable):
        raise err
    if err is not None:
        raise PowerPointUnavailable(f"PowerPoint에 넣지 못했습니다: {err}") from err
    return box["result"]


class PowerPointSender:
    """Controller-facing: one job at a time; returns the number of shapes added."""

    def __init__(self, app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.app_factory = app_factory
        self.timeout = timeout
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def send(self, item) -> int:
        with self._lock:
            if self._busy:
                raise PowerPointBusy("PowerPoint로 보내는 중입니다.")
            self._busy = True
        try:
            return send(item, self.app_factory, self.timeout).added
        finally:
            self._busy = False
