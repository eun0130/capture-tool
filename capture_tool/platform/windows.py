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


# --- whole-window picture (also where the window is covered or off-screen) ----------------------
_gdi = ctypes.WinDLL("gdi32", use_last_error=True)
PW_RENDERFULLCONTENT = 0x2


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowDC.argtypes = [wintypes.HWND]
u32.GetWindowDC.restype = wintypes.HDC
u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi.CreateCompatibleDC.restype = wintypes.HDC
_gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                  wintypes.HANDLE, wintypes.DWORD]
_gdi.CreateDIBSection.restype = wintypes.HBITMAP
_gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi.SelectObject.restype = wintypes.HGDIOBJ
_gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi.DeleteDC.argtypes = [wintypes.HDC]


def capture_window(hwnd: int, frame: Rect):
    """The window's own picture (PrintWindow), cropped to its visible frame `frame` (physical
    px, DWM bounds). BGR numpy image, or None if Windows can't render it."""
    import numpy as np
    wr = wintypes.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(wr)):
        return None
    w, h = wr.right - wr.left, wr.bottom - wr.top
    if w <= 0 or h <= 0 or w * h > 16_000 * 16_000:
        return None
    wdc = u32.GetWindowDC(hwnd)
    mdc = _gdi.CreateCompatibleDC(wdc)
    bits = ctypes.c_void_p()
    bmi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bmp = _gdi.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    try:
        if not bmp or not bits.value:
            return None
        old = _gdi.SelectObject(mdc, bmp)
        ok = u32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
        _gdi.SelectObject(mdc, old)
        if not ok:
            return None
        img = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint8)), shape=(h, w, 4))[:, :, :3].copy()
    finally:
        if bmp:
            _gdi.DeleteObject(bmp)
        _gdi.DeleteDC(mdc)
        u32.ReleaseDC(hwnd, wdc)
    x0, y0 = frame.x - wr.left, frame.y - wr.top           # the invisible resize border around it
    crop = img[max(0, y0):max(0, y0) + frame.h, max(0, x0):max(0, x0) + frame.w]
    return crop if crop.shape[:2] == (frame.h, frame.w) else None
