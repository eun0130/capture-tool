"""Scroll capture helpers on the Mac: wheel events and cursor moves through Quartz (needs the
Accessibility permission), the Escape key state, keeping our own windows out of captures
(NSWindow sharing type), browser checks by bundle id. No DRM-style display affinity exists."""
from __future__ import annotations

from ...core.geometry import Rect

BROWSERS = ("com.apple.Safari", "com.google.Chrome", "com.microsoft.edgemac", "org.mozilla.firefox",
            "company.thebrowser.Browser", "com.brave.Browser", "com.vivaldi.Vivaldi", "com.operasoftware.Opera",
            "com.naver.Whale")


def _scale_at(x: int, y: int) -> float:
    from .screen import _scale_at as at
    return at(Rect(x, y, 1, 1))


def set_cursor(x: int, y: int) -> None:
    from Quartz import CGWarpMouseCursorPosition
    k = _scale_at(x, y)
    CGWarpMouseCursorPosition((x / k, y / k))


def wheel(x: int, y: int, notches: int) -> None:
    """Scroll `notches` lines at (x, y) physical px: negative = down, like WHEEL_DELTA on Windows."""
    from Quartz import CGEventCreateScrollWheelEvent, CGEventPost, kCGHIDEventTap, kCGScrollEventUnitLine
    set_cursor(x, y)
    CGEventPost(kCGHIDEventTap, CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitLine, 1, int(notches)))


def esc_pressed() -> bool:
    from Quartz import CGEventSourceKeyState, kCGEventSourceStateHIDSystemState
    return bool(CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, 0x35))          # kVK_Escape


def display_affinity(hwnd: int) -> int:
    return 0


def exclude_from_capture(hwnd: int) -> bool:
    """`hwnd` is a Qt winId = NSView pointer; its window stops appearing in screen captures."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.platformName() != "cocoa":       # offscreen (tests): winId is not a real NSView
        return False
    import objc
    from AppKit import NSWindowSharingNone
    view = objc.objc_object(c_void_p=int(hwnd))
    win = view.window()
    if win is None:
        return False
    win.setSharingType_(NSWindowSharingNone)
    return True


def _bundle_of(hwnd: int) -> str:
    from AppKit import NSRunningApplication
    from .windows import _describe
    w = _describe(hwnd)
    if not w:
        return ""
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(w.get("kCGWindowOwnerPID", 0)))
    return str(app.bundleIdentifier() or "") if app else ""


def is_browser(hwnd: int) -> bool:
    return _bundle_of(hwnd) in BROWSERS


def browser_viewport(hwnd: int) -> Rect | None:
    """No child-window viewport on the Mac: the scroll capture uses the window as a whole."""
    return None


def root_window_at(x: int, y: int) -> int:
    import os
    from .windows import top_level_windows, window_at
    w = window_at((x, y), top_level_windows(exclude_pid=os.getpid()))
    return w.hwnd if w else 0
