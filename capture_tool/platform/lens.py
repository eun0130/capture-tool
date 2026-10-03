"""Google Lens: after the "이미지로 검색" page is opened, press Ctrl+V there once it is in front,
so the capture is searched without pasting by hand. Only ever into a NEW browser window or tab
whose title says it is that page; anything else in front and nothing is typed."""
from __future__ import annotations

import ctypes
import threading
import time

WAIT_S = 10.0          # the browser may take a while to start
SETTLE_S = 1.2         # the page's paste box is ready a moment after the title appears


def should_paste(is_browser: bool, title: str, want: str, same_as_before: bool) -> bool:
    return bool(is_browser and title and want in title and not same_as_before)


def _title(u32, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def paste_into_new_browser_page(want: str, done=None) -> bool:
    """Starts watching in the background; returns at once. `done(ok)` is called at the end."""
    from . import scroll
    u32 = ctypes.WinDLL("user32")
    before = (int(u32.GetForegroundWindow() or 0), _title(u32, int(u32.GetForegroundWindow() or 0)))

    def run():
        end = time.time() + WAIT_S
        ok = False
        while time.time() < end:
            time.sleep(0.3)
            hwnd = int(u32.GetForegroundWindow() or 0)
            if not hwnd:
                continue
            title = _title(u32, hwnd)
            if not should_paste(scroll.is_browser(hwnd), title, want, (hwnd, title) == before):
                continue
            time.sleep(SETTLE_S)
            if int(u32.GetForegroundWindow() or 0) != hwnd or want not in _title(u32, hwnd):
                break                                  # the person moved on: type nothing
            VK_CONTROL, V, UP = 0x11, 0x56, 0x0002
            u32.keybd_event(VK_CONTROL, 0, 0, 0)
            u32.keybd_event(V, 0, 0, 0)
            u32.keybd_event(V, 0, UP, 0)
            u32.keybd_event(VK_CONTROL, 0, UP, 0)
            ok = True
            break
        if done is not None:
            done(ok)

    threading.Thread(target=run, name="lens-paste", daemon=True).start()
    return True
