"""Windows helpers for scroll capture and capture-protection checks.

- wheel(): move the cursor over the view and send mouse-wheel notches (SendInput), the same
  input a user produces, so every app/browser scrolls its own way.
- browser_viewport(): the page area of a Chromium browser window (Chrome, Edge, Whale …),
  without tabs/address bar, so a full-page capture contains only the page.
- display_affinity(): whether a window asked Windows to hide it from screenshots
  (SetWindowDisplayAffinity). Such windows come out black; that is a security feature of the
  window's owner and is never bypassed.
- exclude_from_capture(): our own progress window stays out of the frames being captured."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from ..core.geometry import Rect

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_MOUSE = 0
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
VK_ESCAPE = 0x1B
WDA_NONE, WDA_MONITOR, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x1, 0x11
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GA_ROOT = 2

BROWSERS = {"chrome.exe", "msedge.exe", "whale.exe", "brave.exe", "opera.exe", "vivaldi.exe",
            "firefox.exe", "naverwhale.exe"}
CHROMIUM_VIEW = "Chrome_RenderWidgetHostHWND"


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
u32.GetAsyncKeyState.restype = ctypes.c_short
u32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetAncestor.restype = wintypes.HWND
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD)]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
_EnumChild = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.EnumChildWindows.argtypes = [wintypes.HWND, _EnumChild, wintypes.LPARAM]


def wheel(x: int, y: int, notches: int) -> None:
    """Scroll the window under (x, y): notches > 0 scrolls up, < 0 down."""
    u32.SetCursorPos(int(x), int(y))
    inp = INPUT(type=INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(notches * WHEEL_DELTA).value, MOUSEEVENTF_WHEEL, 0, 0)
    u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def set_cursor(x: int, y: int) -> None:
    u32.SetCursorPos(int(x), int(y))


def esc_pressed() -> bool:
    """Escape went down since the last call (works while another app has focus)."""
    return bool(u32.GetAsyncKeyState(VK_ESCAPE) & 0x8001)


def display_affinity(hwnd: int) -> int:
    v = wintypes.DWORD()
    if not u32.GetWindowDisplayAffinity(hwnd, ctypes.byref(v)):
        return WDA_NONE
    return int(v.value)


def exclude_from_capture(hwnd: int) -> bool:
    """Hide one of OUR windows from screenshots (Windows 10 2004+); True if it worked."""
    return bool(u32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


def process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        k32.CloseHandle(h)


def is_browser(hwnd: int) -> bool:
    return process_name(hwnd) in BROWSERS


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _rect(hwnd) -> Rect | None:
    r = wintypes.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(r)) or r.right <= r.left or r.bottom <= r.top:
        return None
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def browser_viewport(hwnd: int) -> Rect | None:
    """Largest visible Chromium page view inside the window (DevTools panes are smaller)."""
    best: list[Rect] = []

    def cb(child, _):
        if u32.IsWindowVisible(child) and _class(child) == CHROMIUM_VIEW:
            r = _rect(child)
            if r is not None:
                best.append(r)
        return True

    u32.EnumChildWindows(hwnd, _EnumChild(cb), 0)
    return max(best, key=lambda r: r.w * r.h) if best else None


def root_window_at(x: int, y: int) -> int:
    h = u32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return int(u32.GetAncestor(h, GA_ROOT) or 0) if h else 0
