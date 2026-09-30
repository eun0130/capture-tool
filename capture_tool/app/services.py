"""Real (Windows) implementations of the screen and clipboard services."""
from __future__ import annotations

import os

from ..platform import screen, win_clipboard, windows


class RealScreen:
    def monitors(self):
        return screen.monitors()

    def cursor_pos(self):
        return screen.cursor_pos()

    def grab(self, rect):
        return screen.grab(rect)

    # scroll capture & capture-protection checks
    def wheel(self, x, y, notches):
        from ..platform import scroll
        scroll.wheel(x, y, notches)

    def set_cursor(self, x, y):
        from ..platform import scroll
        scroll.set_cursor(x, y)

    def esc_pressed(self):
        from ..platform import scroll
        return scroll.esc_pressed()

    def display_affinity(self, hwnd):
        from ..platform import scroll
        return scroll.display_affinity(hwnd)

    def is_browser(self, hwnd):
        from ..platform import scroll
        return scroll.is_browser(hwnd)

    def browser_viewport(self, hwnd):
        from ..platform import scroll
        return scroll.browser_viewport(hwnd)

    def root_window_at(self, x, y):
        from ..platform import scroll
        return scroll.root_window_at(x, y)

    def exclude_from_capture(self, hwnd):
        from ..platform import scroll
        return scroll.exclude_from_capture(hwnd)

    def capture_window(self, hwnd, rect):
        return windows.capture_window(hwnd, rect)

    def windows(self):
        try:
            return windows.top_level_windows(exclude_pid=os.getpid())
        except OSError:
            return []


class RealClipboard:
    def __init__(self, hwnd=None):
        self.hwnd = hwnd

    def set(self, payload: dict) -> None:
        win_clipboard.set_formats(payload, retries=10, delay=0.02, hwnd=self.hwnd)
