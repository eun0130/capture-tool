"""OS backends. App code asks `backend()` and uses its screen / clipboard / hotkey / windows /
scroll / startup / secret / shell modules; it never imports an OS module by name. The Windows
modules keep their old names (win_clipboard, win_hotkey, ...); the Mac ones live in platform/mac/.
CAPTURE_PLATFORM=darwin|win32 forces the choice for tests on a developer machine - never in an
installed (frozen) build."""
from __future__ import annotations

import importlib
import os
import sys


class Backend:
    """Lazy module bag: `backend().clipboard` imports the module on first use."""

    def __init__(self, package: str, names: dict[str, str]):
        self._package, self._names = package, names

    def __getattr__(self, item: str):
        names = self.__dict__.get("_names") or {}
        if item not in names:
            raise AttributeError(item)
        mod = importlib.import_module(f"{self._package}.{names[item]}")
        setattr(self, item, mod)
        return mod


_NAMES = ("screen", "clipboard", "hotkey", "windows", "scroll", "startup", "secret", "shell")
WINDOWS = Backend("capture_tool.platform", {"screen": "screen", "clipboard": "win_clipboard", "hotkey": "win_hotkey",
                                            "windows": "windows", "scroll": "scroll", "startup": "startup",
                                            "secret": "secret", "shell": "shell"})
MAC = Backend("capture_tool.platform.mac", {n: n for n in _NAMES})
_override = None


def name() -> str:
    """'win32' or 'darwin'."""
    if not getattr(sys, "frozen", False):
        forced = os.environ.get("CAPTURE_PLATFORM", "").strip().lower()
        if forced in ("win32", "darwin"):
            return forced
    return sys.platform


def is_mac() -> bool:
    return name() == "darwin"


def backend():
    if _override is not None:
        return _override
    return MAC if is_mac() else WINDOWS


def use(b):
    """Swap the backend (tests). Returns the previous override so it can be restored."""
    global _override
    before, _override = _override, b
    return before
