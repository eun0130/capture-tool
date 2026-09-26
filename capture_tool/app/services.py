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
