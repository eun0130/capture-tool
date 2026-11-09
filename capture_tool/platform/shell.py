"""Windows: open a folder or file with its program, show a file in Explorer, open a web/mail link."""
from __future__ import annotations

import os
import subprocess


def open_path(path, runner=None) -> None:
    try:
        (runner or os.startfile)(str(path))
    except OSError:
        pass


def reveal(path, runner=None) -> None:
    try:
        (runner or subprocess.Popen)(["explorer", "/select,", str(path)])
    except OSError:
        pass


def open_url(url: str, runner=None) -> bool:
    """The default browser (https) or mail app (mailto:); other schemes are refused."""
    if not url.startswith(("https://", "mailto:")):
        return False
    try:
        (runner or os.startfile)(url)
        return True
    except OSError:
        return False


def _short_name(path: str) -> str:
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    k32.GetShortPathNameW.restype = ctypes.c_uint32
    buf = ctypes.create_unicode_buffer(1024)
    n = k32.GetShortPathNameW(path, buf, 1024)
    return buf.value if 0 < n < 1024 else path


def _junction(target: str, at: str) -> bool:
    """A folder link (junction): no admin rights needed, unlike a symbolic link."""
    import _winapi
    try:
        if os.path.isdir(at):                      # made earlier for this very folder (the name is its hash)
            return True
        os.makedirs(os.path.dirname(at), exist_ok=True)
        _winapi.CreateJunction(target, at)
        return os.path.isdir(at)
    except OSError:
        return False


def ascii_path(path, short=None, link=None, public=None) -> str:
    """The folder as a library that opens files with narrow (non-Unicode) strings can open it - the AI
    engine failed with "Error opening ...genai_config.json" under C:\\Users\\<Korean name> (BUG-141).
    English-only paths are returned as they are; otherwise the folder's Windows short name, else a
    folder link under Public, else the path unchanged (the engine's own error then names it)."""
    import hashlib
    import ntpath
    s = str(path)
    if s.isascii():
        return s
    try:
        alt = (short or _short_name)(s)
        if alt and alt.isascii():
            return alt
        base = public or os.environ.get("PUBLIC") or r"C:\Users\Public"
        at = ntpath.join(base, "CaptureTool", "link-" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:12])
        if at.isascii() and (link or _junction)(s, at):
            return at
    except Exception:  # noqa: BLE001 - never worse than the original path
        pass
    return s

