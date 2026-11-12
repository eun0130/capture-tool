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
    """BGRA image (zero-copy view of the grab buffer) of a physical-pixel rectangle.
    Callers convert only the pixels they need; converting a whole 4K frame costs ~30 ms."""
    shot = _mss().grab({"left": r.x, "top": r.y, "width": r.w, "height": r.h})
    return np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)


# --- the still picture behind the capture screen (BUG-142) ------------------------------------------
_cams: dict = {}


def _dxgi_grab(r: Rect):
    """BGRA picture of `r` through DXGI desktop duplication - what the monitor really shows, GPU-drawn
    windows included - or None. The whole output is grabbed (duplication hands out the latest frame of
    an output, not of a region) and cut to `r`."""
    import time
    import dxcam
    factory = vars(dxcam)["__factory"]
    for d, outputs in enumerate(factory.outputs):
        for o, out in enumerate(outputs):
            out.update_desc()
            c = out.desc.DesktopCoordinates
            if not (c.left <= r.x and c.top <= r.y and r.x + r.w <= c.right and r.y + r.h <= c.bottom):
                continue
            cam = _cams.get((d, o))
            if cam is None or getattr(cam, "is_released", False):
                cam = _cams[(d, o)] = dxcam.create(device_idx=d, output_idx=o, output_color="BGRA")
            frame = None
            for _ in range(10):                           # the very first frame can take a moment
                frame = cam.grab(new_frame_only=False)
                if frame is not None:
                    break
                time.sleep(0.01)
            if frame is None:
                return None
            x, y = r.x - c.left, r.y - c.top
            return np.ascontiguousarray(frame[y:y + r.h, x:x + r.w])
    return None


def grab_frame(r: Rect) -> np.ndarray:
    """The still picture for the capture screen (BGRA, like grab): DXGI when it has the picture, the
    GDI grab otherwise - GDI gave white for Windows Terminal (herdr) and other GPU-drawn windows."""
    from ..core.frames import still_frame
    return still_frame(r, _dxgi_grab, lambda rr: np.ascontiguousarray(grab(rr)))


def recording_grabber(rect: Rect):
    """A grab for the recording thread: the still-frame way (DXGI, so GPU-drawn windows are not white,
    BUG-142; GDI when DXGI has no picture). Our own windows marked exclude-from-capture stay out."""
    return grab_frame


def mouse_reader(rect: Rect):
    """(x, y in physical px, left button down) - GetCursorPos / GetAsyncKeyState work on any thread."""
    def read() -> tuple[int, int, bool]:
        p = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y, bool(u32.GetAsyncKeyState(0x01) & 0x8000)          # VK_LBUTTON
    return read


def self_check() -> list[str]:
    """For --check-backend: what the built app must be able to load beyond the module itself."""
    try:
        import dxcam  # noqa: F401
        return []
    except Exception as e:  # noqa: BLE001
        return [f"dxcam: {e}"]

