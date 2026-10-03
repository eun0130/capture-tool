"""KakaoTalk PC: find it, bring an open chat (or KakaoTalk itself) to the front, paste the
clipboard there. KakaoTalk has no public sending API; pasting a picture opens its own send
confirmation, so the person always presses 전송 themselves - nothing is sent automatically."""
from __future__ import annotations

import os
import time
from pathlib import Path

WINDOW_CLASS = "EVA_Window_Dblclk"
MAIN_TITLE = "카카오톡"
NOT_CHATS = {MAIN_TITLE, "톡캘린더", "브리핑 보드", "카카오톡 설정", "알림", "공지"}


def main_window(windows) -> int:
    """windows: (hwnd, class, title, visible) of KakaoTalk's top-level windows."""
    for hwnd, cls, title, _visible in windows:
        if cls == WINDOW_CLASS and title == MAIN_TITLE:
            return hwnd
    return 0


def chat_windows(windows) -> list[tuple[int, str]]:
    return [(hwnd, title) for hwnd, cls, title, visible in windows
            if cls == WINDOW_CLASS and visible and title and title not in NOT_CHATS]


def exe_path() -> Path | None:
    import winreg
    for root, key in [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\KakaoTalk"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\KakaoTalk"),
                      (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\KakaoTalk")]:
        try:
            with winreg.OpenKey(root, key) as k:
                p = Path(str(winreg.QueryValueEx(k, "DisplayIcon")[0]).split(",")[0].strip('"'))
                if p.is_file():
                    return p
        except OSError:
            continue
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        p = Path(base) / "Kakao" / "KakaoTalk" / "KakaoTalk.exe"
        if base and p.is_file():
            return p
    return None


def _windows() -> list[tuple[int, str, str, bool]]:
    """Top-level windows that belong to KakaoTalk.exe."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    out = []
    proc_ok: dict[int, bool] = {}

    def is_kakao(pid: int) -> bool:
        if pid not in proc_ok:
            h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
            ok = False
            if h:
                buf = ctypes.create_unicode_buffer(520)
                n = wintypes.DWORD(520)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    ok = buf.value.lower().endswith("\\kakaotalk.exe")
                k32.CloseHandle(h)
            proc_ok[pid] = ok
        return proc_ok[pid]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if is_kakao(pid.value):
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(hwnd, cls, 64)
            title = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, title, 256)
            out.append((int(hwnd), cls.value, title.value, bool(u32.IsWindowVisible(hwnd))))
        return True
    u32.EnumWindows(cb, 0)
    return out


def _front(hwnd: int) -> bool:
    from .powerpoint import bring_to_front
    return bool(bring_to_front(hwnd))


class KakaoSender:
    """What the controller uses (a fake stands in for it in tests)."""

    def installed(self) -> bool:
        return exe_path() is not None or bool(main_window(_windows()))

    def chats(self) -> list[tuple[int, str]]:
        try:
            return chat_windows(_windows())
        except OSError:
            return []

    def open_main(self, wait: float = 8.0) -> bool:
        hwnd = main_window(_windows())
        if not hwnd:
            exe = exe_path()
            if exe is None:
                return False
            os.startfile(str(exe))                                # starts it or shows the running one
            end = time.time() + wait
            while time.time() < end and not hwnd:
                time.sleep(0.25)
                hwnd = main_window(_windows())
        return bool(hwnd) and _front(hwnd)

    def paste_into(self, hwnd: int) -> bool:
        """Bring the chat to the front and press Ctrl+V there - only if that chat really is
        the active window now (otherwise nothing is typed anywhere)."""
        import ctypes
        if not any(h == hwnd for h, _ in self.chats()):
            return False
        if not _front(hwnd):
            return False
        time.sleep(0.25)
        u32 = ctypes.WinDLL("user32")
        if int(u32.GetForegroundWindow() or 0) != hwnd:
            return False
        VK_CONTROL, V, UP = 0x11, 0x56, 0x0002
        u32.keybd_event(VK_CONTROL, 0, 0, 0)
        u32.keybd_event(V, 0, 0, 0)
        u32.keybd_event(V, 0, UP, 0)
        u32.keybd_event(VK_CONTROL, 0, UP, 0)
        return True
