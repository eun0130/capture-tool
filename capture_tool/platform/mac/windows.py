"""Windows on screen through Quartz (CGWindowList). Ids are CGWindowNumbers; frames are top-left
physical px like the Windows backend (kCGWindowBounds is already top-left in screen points, only
the Retina scale is applied). Window names need the Screen Recording permission."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...core.geometry import Rect
from .screen import to_physical


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: Rect
    pid: int = 0


def _scale() -> float:
    from PySide6.QtGui import QGuiApplication
    return float(QGuiApplication.primaryScreen().devicePixelRatio())


def _describe(hwnd: int) -> dict | None:
    from Quartz import CGWindowListCreateDescriptionFromArray
    for w in CGWindowListCreateDescriptionFromArray([int(hwnd)]) or []:
        return dict(w)
    return None


def top_level_windows(exclude_pid: int | None = None) -> list[WindowInfo]:
    """Front-most first (CGWindowList order); menu bar, desktop and tiny windows left out."""
    from Quartz import (CGWindowListCopyWindowInfo, kCGNullWindowID, kCGWindowListExcludeDesktopElements,
                        kCGWindowListOptionOnScreenOnly)
    k = _scale()
    out = []
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
                                        kCGNullWindowID) or []:
        if int(w.get("kCGWindowLayer", 0)) != 0 or int(w.get("kCGWindowOwnerPID", 0)) == exclude_pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        r = to_physical(Rect(int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0))), k)
        if r.w < 8 or r.h < 8:
            continue
        title = str(w.get("kCGWindowName") or w.get("kCGWindowOwnerName") or "")
        out.append(WindowInfo(int(w["kCGWindowNumber"]), title, r, int(w.get("kCGWindowOwnerPID", 0))))
    return out


def window_at(p, wins: list[WindowInfo]) -> WindowInfo | None:
    x, y = p
    for w in wins:
        if w.rect.x <= x < w.rect.x + w.rect.w and w.rect.y <= y < w.rect.y + w.rect.h:
            return w
    return None


def process_name(hwnd: int) -> str:
    w = _describe(hwnd)
    return str(w.get("kCGWindowOwnerName") or "") if w else ""


def capture_window(hwnd: int, frame: Rect):
    """BGR pixels of one window (its own content, even if covered)."""
    from Quartz import (CGDataProviderCopyData, CGImageGetBytesPerRow, CGImageGetDataProvider, CGImageGetHeight,
                        CGImageGetWidth, CGRectNull, CGWindowListCreateImage, kCGWindowImageBoundsIgnoreFraming,
                        kCGWindowListOptionIncludingWindow)
    img = CGWindowListCreateImage(CGRectNull, kCGWindowListOptionIncludingWindow, int(hwnd),
                                  kCGWindowImageBoundsIgnoreFraming)
    if img is None:
        return None
    w, h, stride = CGImageGetWidth(img), CGImageGetHeight(img), CGImageGetBytesPerRow(img)
    data = bytes(CGDataProviderCopyData(CGImageGetDataProvider(img)))
    arr = np.frombuffer(data, np.uint8).reshape(h, stride // 4, 4)[:, :w, :3]          # BGRA -> BGR
    return np.ascontiguousarray(arr)


def bring_to_front(hwnd: int) -> bool:
    from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
    w = _describe(hwnd)
    if not w:
        return False
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(w.get("kCGWindowOwnerPID", 0)))
    return bool(app and app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
