"""Real implementations of the screen and clipboard services on top of the OS backend
(platform.backend(): Windows modules or platform/mac)."""
from __future__ import annotations

import os

from .. import platform as pf


def _b():
    return pf.backend()


class RealScreen:
    def monitors(self):
        return _b().screen.monitors()

    def cursor_pos(self):
        return _b().screen.cursor_pos()

    def grab(self, rect):
        return _b().screen.grab(rect)

    # scroll capture & capture-protection checks
    def wheel(self, x, y, notches):
        _b().scroll.wheel(x, y, notches)

    def set_cursor(self, x, y):
        _b().scroll.set_cursor(x, y)

    def esc_pressed(self):
        return _b().scroll.esc_pressed()

    def display_affinity(self, hwnd):
        return _b().scroll.display_affinity(hwnd)

    def paste_into_new_browser_page(self, want):
        from ..platform import lens                        # Windows only: edition hides 'lens' on the Mac
        return lens.paste_into_new_browser_page(want)

    def is_browser(self, hwnd):
        return _b().scroll.is_browser(hwnd)

    def browser_viewport(self, hwnd):
        return _b().scroll.browser_viewport(hwnd)

    def root_window_at(self, x, y):
        return _b().scroll.root_window_at(x, y)

    def exclude_from_capture(self, hwnd):
        return _b().scroll.exclude_from_capture(hwnd)

    def capture_window(self, hwnd, rect):
        return _b().windows.capture_window(hwnd, rect)

    def process_name(self, hwnd):
        return _b().windows.process_name(hwnd)

    def windows(self):
        try:
            return _b().windows.top_level_windows(exclude_pid=os.getpid())
        except OSError:
            return []


class RealClipboard:
    def __init__(self, hwnd=None):
        self.hwnd = hwnd

    def set(self, payload: dict) -> None:
        _b().clipboard.set_formats(payload, retries=10, delay=0.02, hwnd=self.hwnd)
