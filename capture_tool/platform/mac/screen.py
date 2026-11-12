"""macOS screen: monitors and the cursor from Qt (logical px x devicePixelRatio = physical px),
pictures from mss. AppKit / Quartz report some rectangles with a bottom-left origin; the app wants
top-left physical px like the Windows backend, so the flip lives here and nowhere else."""
from __future__ import annotations

import numpy as np

from ...core.geometry import Monitor, Rect


def flip_rect(q: tuple[float, float, float, float], main_height: float) -> Rect:
    """AppKit (x, y, w, h) with y up from the main display's bottom -> top-left logical rect."""
    x, y, w, h = q
    return Rect(int(round(x)), int(round(main_height - y - h)), int(round(w)), int(round(h)))


def to_physical(r: Rect, scale: float) -> Rect:
    return Rect(int(round(r.x * scale)), int(round(r.y * scale)), int(round(r.w * scale)), int(round(r.h * scale)))


def set_dpi_awareness() -> None:
    """Nothing to do: Qt is Retina-aware on the Mac."""


def monitors() -> list[Monitor]:
    from PySide6.QtGui import QGuiApplication
    out = []
    primary = QGuiApplication.primaryScreen()
    for i, s in enumerate(QGuiApplication.screens()):
        g, k = s.geometry(), float(s.devicePixelRatio())
        out.append(Monitor(i, to_physical(Rect(g.x(), g.y(), g.width(), g.height()), k), k, s is primary, s.name()))
    return out


def cursor_pos() -> tuple[int, int]:
    from PySide6.QtGui import QCursor, QGuiApplication
    p = QCursor.pos()
    s = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
    k = float(s.devicePixelRatio())
    return int(round(p.x() * k)), int(round(p.y() * k))


def _scale_at(r: Rect) -> float:
    for m in monitors():
        if m.rect.x <= r.x < m.rect.x + m.rect.w and m.rect.y <= r.y < m.rect.y + m.rect.h:
            return m.scale or 1.0
    return 1.0


def _mss():
    import mss
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()             # mss 10 deprecates mss.mss


def _grab_with(sct, r: Rect, k: float) -> np.ndarray:
    shot = sct.grab({"left": int(round(r.x / k)), "top": int(round(r.y / k)),
                     "width": max(1, int(round(r.w / k))), "height": max(1, int(round(r.h / k)))})
    img = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3]
    if img.shape[1] != r.w or img.shape[0] != r.h:
        import cv2
        img = cv2.resize(img, (r.w, r.h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


def grab(r: Rect) -> np.ndarray:
    """BGR pixels of a physical rect. mss takes logical coordinates on the Mac and returns the
    physical pixels of a Retina display; the result is resized to the asked size if they differ."""
    with _mss() as sct:
        return _grab_with(sct, r, _scale_at(r))


def recording_grabber(rect: Rect):
    """A grab for the recording thread: the display scale is read now (Qt, GUI thread); the screen
    reader is opened on the recording thread at its first picture and kept for the next ones."""
    k, box = _scale_at(rect), {}

    def grab_(r: Rect) -> np.ndarray:
        if "sct" not in box:
            box["sct"] = _mss()
        return _grab_with(box["sct"], r, k)
    return grab_


def mouse_reader(rect: Rect):
    """(x, y in physical px, left button down) from Quartz - safe on any thread."""
    k = _scale_at(rect)

    def read() -> tuple[int, int, bool]:
        from Quartz import (CGEventCreate, CGEventGetLocation, CGEventSourceButtonState,
                            kCGEventSourceStateHIDSystemState, kCGMouseButtonLeft)
        p = CGEventGetLocation(CGEventCreate(None))
        down = CGEventSourceButtonState(kCGEventSourceStateHIDSystemState, kCGMouseButtonLeft)
        return int(round(p.x * k)), int(round(p.y * k)), bool(down)
    return read


def grab_frame(r: Rect) -> np.ndarray:
    """The still picture for the capture screen: Quartz already sees every window (the Windows backend
    needs DXGI for GPU-drawn ones, BUG-142)."""
    return grab(r)

