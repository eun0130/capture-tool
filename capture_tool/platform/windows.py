"""Visible top-level windows in z-order, for click-to-select a window while capturing."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from ..core.geometry import Rect

u32 = ctypes.WinDLL("user32", use_last_error=True)
dwm = ctypes.WinDLL("dwmapi")
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.EnumWindows.argtypes = [_EnumProc, wintypes.LPARAM]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsIconic.argtypes = [wintypes.HWND]
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: Rect


def _cloaked(hwnd) -> bool:
    v = wintypes.DWORD()
    if dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v)) != 0:
        return False
    return v.value != 0


def _frame(hwnd) -> Rect | None:
    r = wintypes.RECT()
    if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
    if r.right - r.left <= 0 or r.bottom - r.top <= 0:
        return None
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def top_level_windows(exclude_pid: int | None = None) -> list[WindowInfo]:
    """Topmost first. Skips hidden, minimized, cloaked, tool and click-through windows."""
    out: list[WindowInfo] = []

    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd) or u32.IsIconic(hwnd) or _cloaked(hwnd):
            return True
        ex = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & (WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT):
            return True
        if exclude_pid is not None:
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == exclude_pid:
                return True
        rect = _frame(hwnd)
        if rect is None:
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        out.append(WindowInfo(int(hwnd), buf.value, rect))
        return True

    u32.EnumWindows(_EnumProc(cb), 0)
    return out


def window_at(p, wins: list[WindowInfo]) -> WindowInfo | None:
    for w in wins:
        if w.rect.contains(p):
            return w
    return None
