"""Hotkey parsing, validation and conflict checks (maps to Win32 RegisterHotKey)."""
from __future__ import annotations

from dataclasses import dataclass

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt",
    "shift": "shift",
    "win": "win", "windows": "win", "cmd": "win", "command": "win", "meta": "win", "super": "win",
}
_MOD_ORDER = ["ctrl", "alt", "shift", "win"]
_MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
_MOD_FLAG = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}

_VK: dict[str, int] = {}
_VK.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
_VK.update({str(d): 0x30 + d for d in range(10)})
_VK.update({f"F{n}": 0x6F + n for n in range(1, 25)})
_VK.update({
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
    "PrintScreen": 0x2C, "Tab": 0x09, "Space": 0x20, "Delete": 0x2E, "Insert": 0x2D,
    "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Pause": 0x13, "Escape": 0x1B,
})
_KEY_ALIASES = {
    "~": "`", "backtick": "`", "grave": "`", "tilde": "`",
    "prtsc": "PrintScreen", "prtscn": "PrintScreen", "print": "PrintScreen", "printscreen": "PrintScreen",
    "del": "Delete", "ins": "Insert", "esc": "Escape", "pgup": "PageUp", "pgdn": "PageDown",
}
_KEY_LABEL = {"`": "~"}
# Keys that may be used without a modifier
_STANDALONE = {f"F{n}" for n in range(1, 25)} | {"PrintScreen", "Pause"}

_RESERVED = [
    "Win+L", "Win+D", "Win+E", "Win+R", "Win+I", "Win+X", "Win+Tab", "Win+Shift+S",
    "Ctrl+Alt+Delete", "Ctrl+Shift+Escape",
    "Alt+F4", "Alt+Tab",
    "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+Y", "Ctrl+A", "Ctrl+S",
]
_CONFLICTS = {
    "Ctrl+`": "VS Code 터미널 열기 단축키와 겹칩니다.",
    "PrintScreen": "Windows 11에서 기본으로 캡처 도구를 여는 키입니다.",
    "Win+Shift+S": "Windows 캡처 도구 단축키와 겹칩니다.",
    "Ctrl+Shift+`": "VS Code 새 터미널 단축키와 겹칩니다.",
}


class HotkeyError(ValueError):
    pass


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset
    key: str

    @property
    def vk(self) -> int:
        return _VK[self.key]

    @property
    def flags(self) -> int:
        f = MOD_NOREPEAT
        for m in self.mods:
            f |= _MOD_FLAG[m]
        return f

    def __str__(self) -> str:
        parts = [_MOD_LABEL[m] for m in _MOD_ORDER if m in self.mods]
        parts.append(_KEY_LABEL.get(self.key, self.key))
        return " + ".join(parts)


def _canonical_key(token: str) -> str | None:
    t = token.strip()
    low = t.lower()
    if low in _KEY_ALIASES:
        return _KEY_ALIASES[low]
    for k in _VK:
        if k.lower() == low:
            return k
    return None


def parse(text: str) -> Hotkey:
    if text is None or not text.strip():
        raise HotkeyError("단축키가 비어 있습니다.")
    parts = [p.strip() for p in text.split("+")]
    if any(p == "" for p in parts):
        raise HotkeyError(f"잘못된 단축키 형식: {text!r}")
    mods: set[str] = set()
    key: str | None = None
    for p in parts:
        m = _MOD_ALIASES.get(p.lower())
        if m:
            mods.add(m)
            continue
        k = _canonical_key(p)
        if k is None:
            raise HotkeyError(f"알 수 없는 키: {p!r}")
        if key is not None:
            raise HotkeyError("일반 키는 하나만 지정할 수 있습니다.")
        key = k
    if key is None:
        raise HotkeyError("수정키(Ctrl/Alt/Shift/Win) 외에 일반 키가 하나 필요합니다.")
    if not mods and key not in _STANDALONE:
        raise HotkeyError("Ctrl, Alt, Shift, Win 중 하나 이상과 함께 눌러야 합니다.")
    return Hotkey(frozenset(mods), key)


_RESERVED_SET = {parse(s) for s in _RESERVED}
_CONFLICT_MAP = {parse(k): v for k, v in _CONFLICTS.items()}


def is_reserved(hk: Hotkey) -> bool:
    return hk in _RESERVED_SET


def known_conflicts(hk: Hotkey) -> list[str]:
    msg = _CONFLICT_MAP.get(hk)
    return [msg] if msg else []


def find_duplicates(bindings: dict[str, Hotkey]) -> list[tuple[str, str]]:
    items = list(bindings.items())
    dups = []
    for i, (a, ha) in enumerate(items):
        for b, hb in items[i + 1:]:
            if ha == hb:
                dups.append((a, b))
    return dups
