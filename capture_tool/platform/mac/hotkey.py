"""macOS global hot keys through Carbon RegisterEventHotKey (no permission needed). The Carbon
event handler runs on the main thread inside the Qt event loop (Qt pumps the Cocoa run loop); it
puts the hot key id on a queue that a Qt timer drains and hands to HotkeyManager.dispatch.
`carbon_keys` is pure and tested on every OS; the registration bodies need a Mac."""
from __future__ import annotations

import ctypes
import queue

from ...core.hotkey import Hotkey

cmdKey, shiftKey, optionKey, controlKey = 0x0100, 0x0200, 0x0800, 0x1000
_MODS = {"win": cmdKey, "shift": shiftKey, "alt": optionKey, "ctrl": controlKey}
# kVK_* virtual key codes (Carbon HIToolbox/Events.h), ANSI layout
_VK = {"A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05, "Z": 0x06, "X": 0x07, "C": 0x08, "V": 0x09,
       "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E, "R": 0x0F, "Y": 0x10, "T": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
       "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
       "O": 0x1F, "U": 0x20, "[": 0x21, "I": 0x22, "P": 0x23, "L": 0x25, "J": 0x26, "'": 0x27, "K": 0x28, ";": 0x29,
       "\\": 0x2A, ",": 0x2B, "/": 0x2C, "N": 0x2D, "M": 0x2E, ".": 0x2F, "Tab": 0x30, "Space": 0x31, "`": 0x32,
       "Escape": 0x35, "F5": 0x60, "F6": 0x61, "F7": 0x62, "F3": 0x63, "F8": 0x64, "F9": 0x65, "F11": 0x67,
       "F13": 0x69, "F14": 0x6B, "F10": 0x6D, "F12": 0x6F, "F15": 0x71, "Insert": 0x72, "Home": 0x73,
       "PageUp": 0x74, "Delete": 0x75, "F4": 0x76, "End": 0x77, "F2": 0x78, "PageDown": 0x79, "F1": 0x7A,
       "Left": 0x7B, "Right": 0x7C, "Down": 0x7D, "Up": 0x7E}
SIGNATURE = 0x43505452                 # 'CPTR'


class UnsupportedKey(ValueError):
    pass


def carbon_keys(hk: Hotkey) -> tuple[int, int]:
    """(virtual key code, modifier mask) for RegisterEventHotKey."""
    if hk.key not in _VK:
        raise UnsupportedKey(f"{hk.key} 키는 맥에서 쓸 수 없습니다.")
    mods = 0
    for m in hk.mods:
        mods |= _MODS[m]
    return _VK[hk.key], mods


# --- registration (Mac only) ---------------------------------------------------------------------
_queue: "queue.Queue[int]" = queue.Queue()
_refs: dict[int, object] = {}          # hot key id -> EventHotKeyRef (kept alive for unregister)
_keep: list = []                       # the handler callback, the Qt timer
_dispatch = None


def set_dispatch(fn) -> None:
    """HotkeyWindow calls this once: hot key ids reach `fn` on the GUI thread through a timer."""
    global _dispatch
    _dispatch = fn
    from PySide6.QtCore import QTimer
    t = QTimer()
    t.setInterval(30)
    t.timeout.connect(_drain)
    t.start()
    _keep.append(t)


def _drain() -> None:
    while True:
        try:
            hk_id = _queue.get_nowait()
        except queue.Empty:
            return
        if _dispatch is not None:
            _dispatch(hk_id)


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


# OSStatus handler(EventHandlerCallRef, EventRef, void *userData)
HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
CARBON_FUNCTIONS = ("GetApplicationEventTarget", "InstallEventHandler", "GetEventParameter",
                    "RegisterEventHotKey", "UnregisterEventHotKey")


def _declare(lib) -> None:
    """Carbon signatures (Carbon/CarbonEvents.h). Without argtypes ctypes passes Python ints as
    32-bit C ints, which truncates 64-bit EventRefs / ByteCounts on arm64 (MAC-09)."""
    c = ctypes
    lib.GetApplicationEventTarget.restype, lib.GetApplicationEventTarget.argtypes = c.c_void_p, []
    lib.InstallEventHandler.restype = c.c_int32
    lib.InstallEventHandler.argtypes = [c.c_void_p, HANDLER, c.c_size_t, c.POINTER(EventTypeSpec), c.c_void_p,
                                        c.c_void_p]
    lib.GetEventParameter.restype = c.c_int32
    lib.GetEventParameter.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.POINTER(c.c_uint32), c.c_size_t,
                                      c.POINTER(c.c_size_t), c.POINTER(EventHotKeyID)]
    lib.RegisterEventHotKey.restype = c.c_int32
    lib.RegisterEventHotKey.argtypes = [c.c_uint32, c.c_uint32, EventHotKeyID, c.c_void_p, c.c_uint32,
                                        c.POINTER(c.c_void_p)]
    lib.UnregisterEventHotKey.restype, lib.UnregisterEventHotKey.argtypes = c.c_int32, [c.c_void_p]


def _carbon():
    """The Carbon framework and the installed hot-key event handler (installed once)."""
    import ctypes.util
    if "carbon" in _refs:
        return _refs["carbon"]
    lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Carbon"))
    _declare(lib)

    def on_hotkey(next_handler, event, user_data):
        hk = EventHotKeyID()
        # kEventParamDirectObject = '----', typeEventHotKeyID = 'hkid'
        lib.GetEventParameter(event, 0x2D2D2D2D, 0x686B6964, None, ctypes.sizeof(hk), None, ctypes.byref(hk))
        if hk.signature == SIGNATURE:
            _queue.put(int(hk.id))
        return 0

    cb = HANDLER(on_hotkey)
    _keep.append(cb)
    spec = EventTypeSpec(0x6B657962, 5)                    # kEventClassKeyboard 'keyb', kEventHotKeyPressed
    target = lib.GetApplicationEventTarget()
    _keep.append(spec)
    lib.InstallEventHandler(target, cb, 1, ctypes.byref(spec), None, None)
    _refs["carbon"] = (lib, target)
    return _refs["carbon"]


def register(hwnd, hotkey_id: int, hk: Hotkey) -> bool:
    try:
        vk, mods = carbon_keys(hk)
    except UnsupportedKey:
        return False
    lib, target = _carbon()
    ref = ctypes.c_void_p()
    status = lib.RegisterEventHotKey(vk, mods, EventHotKeyID(SIGNATURE, hotkey_id), target, 0, ctypes.byref(ref))
    if status != 0:
        return False
    _refs[hotkey_id] = ref
    return True


def unregister(hwnd, hotkey_id: int) -> None:
    ref = _refs.pop(hotkey_id, None)
    if ref is not None:
        _carbon()[0].UnregisterEventHotKey(ref)
