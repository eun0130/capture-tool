"""Global hotkey registration with conflict messages, plus the hidden window receiving WM_HOTKEY."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from ..core.hotkey import HotkeyError, known_conflicts, parse

IDS = {"capture": 0xA001, "ocr": 0xA002, "shapes": 0xA003, "fullscreen": 0xA004, "scroll": 0xA005}
WM_HOTKEY = 0x0312


class HotkeyManager(QObject):
    triggered = Signal(str)

    def __init__(self, register, unregister):
        super().__init__()
        self._register = register
        self._unregister = unregister
        self._active: set[int] = set()

    def id_for(self, action: str) -> int:
        return IDS[action]

    def apply(self, hotkeys: dict) -> dict[str, str]:
        """(Re)register all hotkeys. Returns {action: reason} for the ones that failed."""
        for hk_id in list(self._active):
            self._unregister(hk_id)
        self._active.clear()
        failures: dict[str, str] = {}
        for action, text in hotkeys.items():
            if action not in IDS or not text:
                continue
            try:
                hk = parse(text)
            except HotkeyError as e:
                failures[action] = str(e)
                continue
            if self._register(IDS[action], hk):
                self._active.add(IDS[action])
            else:
                hint = known_conflicts(hk)
                failures[action] = (f"{hk} 단축키를 등록하지 못했습니다. "
                                    + (hint[0] if hint else "다른 프로그램이 이미 사용 중입니다."))
        return failures

    def dispatch(self, hk_id: int) -> None:
        for action, i in IDS.items():
            if i == hk_id:
                self.triggered.emit(action)


class HotkeyWindow(QWidget):
    """Hidden native window that owns the hotkeys and receives WM_HOTKEY."""

    def __init__(self):
        super().__init__()
        from ..platform import win_hotkey
        self.hwnd = int(self.winId())
        self.manager = HotkeyManager(
            register=lambda i, hk: win_hotkey.register(self.hwnd, i, hk),
            unregister=lambda i: win_hotkey.unregister(self.hwnd, i),
        )

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" or event_type == "windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.manager.dispatch(int(msg.wParam))
                return True, 0
        return False, 0
