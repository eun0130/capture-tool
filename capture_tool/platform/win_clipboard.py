"""Write several clipboard formats at once (Win32), retrying while another app holds it."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from ..core.clipboard_payload import DIB, UNICODE

CF_UNICODETEXT = 13
CF_DIB = 8
GMEM_MOVEABLE = 0x0002
_STANDARD = {UNICODE: CF_UNICODETEXT, DIB: CF_DIB}

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32.OpenClipboard.argtypes = [wintypes.HWND]
u32.OpenClipboard.restype = wintypes.BOOL
u32.CloseClipboard.restype = wintypes.BOOL
u32.EmptyClipboard.restype = wintypes.BOOL
u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
u32.SetClipboardData.restype = wintypes.HANDLE
u32.GetClipboardData.argtypes = [wintypes.UINT]
u32.GetClipboardData.restype = wintypes.HANDLE
u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
u32.RegisterClipboardFormatW.restype = wintypes.UINT
k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = wintypes.HGLOBAL
k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
k32.GlobalSize.argtypes = [wintypes.HGLOBAL]
k32.GlobalSize.restype = ctypes.c_size_t
k32.GlobalFree.argtypes = [wintypes.HGLOBAL]


class ClipboardBusy(OSError):
    pass


def format_id(name: str) -> int:
    return _STANDARD.get(name) or u32.RegisterClipboardFormatW(name)


def _open(retries: int, delay: float, hwnd=None) -> None:
    for _ in range(max(1, retries)):
        if u32.OpenClipboard(hwnd):
            return
        time.sleep(delay)
    raise ClipboardBusy("다른 프로그램이 클립보드를 사용 중입니다. 잠시 후 다시 시도하세요.")


def _to_bytes(name: str, value) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-16-le") + b"\x00\x00"
    return bytes(value)


def set_formats(payload: dict, retries: int = 5, delay: float = 0.02, hwnd=None) -> None:
    """hwnd: pass the app's window so it becomes the clipboard owner."""
    if not payload:
        raise ValueError("empty clipboard payload")
    _open(retries, delay, hwnd)
    try:
        u32.EmptyClipboard()
        for name, value in payload.items():
            data = _to_bytes(name, value)
            h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                raise MemoryError("GlobalAlloc failed")
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            if not u32.SetClipboardData(format_id(name), h):
                k32.GlobalFree(h)
                raise OSError(ctypes.get_last_error(), f"SetClipboardData failed for {name}")
    finally:
        u32.CloseClipboard()


def get_format(name: str, retries: int = 5, delay: float = 0.02) -> bytes | None:
    _open(retries, delay)
    try:
        h = u32.GetClipboardData(format_id(name))
        if not h:
            return None
        p = k32.GlobalLock(h)
        try:
            return ctypes.string_at(p, k32.GlobalSize(h))
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def get_text() -> str | None:
    raw = get_format(UNICODE)
    if raw is None:
        return None
    return raw.decode("utf-16-le").split("\x00", 1)[0]
