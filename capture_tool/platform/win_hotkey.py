"""Global hotkeys via RegisterHotKey. WM_HOTKEY arrives at the given window
(or the calling thread's queue when hwnd is None)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..core.hotkey import Hotkey

WM_HOTKEY = 0x0312

u32 = ctypes.WinDLL("user32", use_last_error=True)
u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
u32.RegisterHotKey.restype = wintypes.BOOL
u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
u32.UnregisterHotKey.restype = wintypes.BOOL


def register(hwnd, hotkey_id: int, hk: Hotkey) -> bool:
    """False when another program (or this one) already owns the combination."""
    return bool(u32.RegisterHotKey(hwnd, hotkey_id, hk.flags, hk.vk))


def unregister(hwnd, hotkey_id: int) -> None:
    u32.UnregisterHotKey(hwnd, hotkey_id)
