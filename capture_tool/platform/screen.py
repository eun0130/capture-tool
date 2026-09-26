"""Monitors (physical pixels, per-monitor DPI), cursor position and fast region grabs."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

import numpy as np

from ..core.geometry import Monitor, Rect

u32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    shcore = ctypes.WinDLL("shcore")
except OSError:  # pragma: no cover - very old Windows
    shcore = None

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
MONITORINFOF_PRIMARY = 1


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


_MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
u32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MonitorEnumProc, wintypes.LPARAM]
u32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]


def set_dpi_awareness() -> None:
    """Work in physical pixels. Qt already does this; call it for non-Qt use (tests, tools)."""
    try:
        u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except (AttributeError, OSError):
        pass


def _scale(hmon) -> float:
    if shcore is None:
        return 1.0
    x, y = wintypes.UINT(), wintypes.UINT()
    if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y)) != 0:
        return 1.0
    return x.value / 96.0


def monitors() -> list[Monitor]:
    found: list[Monitor] = []

    def cb(hmon, hdc, lprect, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        u32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        m = Monitor(id=len(found), rect=Rect(r.left, r.top, r.right - r.left, r.bottom - r.top),
                    scale=_scale(hmon), primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    name=info.szDevice)
        found.append(m)
        return True

    u32.EnumDisplayMonitors(None, None, _MonitorEnumProc(cb), 0)
    return found


def cursor_pos() -> tuple[int, int]:
    p = wintypes.POINT()
    u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


_local = threading.local()


def _mss():
    inst = getattr(_local, "mss", None)
    if inst is None:
        import mss
        inst = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        _local.mss = inst
    return inst


def grab(r: Rect) -> np.ndarray:
    """BGR image of a physical-pixel rectangle of the virtual screen."""
    shot = _mss().grab({"left": r.x, "top": r.y, "width": r.w, "height": r.h})
    return np.asarray(shot, dtype=np.uint8)[:, :, :3].copy()
