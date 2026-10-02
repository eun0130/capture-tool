"""File names for saved captures: pattern tokens, Windows-safe names, unique paths."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
MAX_LEN = 200
PATH_LIMIT = 250          # a little under Windows' 260-character MAX_PATH
MIN_STEM = 8


class SaveDirError(OSError):
    pass


def render(pattern: str, now: datetime) -> str:
    tokens = {
        "date": now.strftime("%Y%m%d"),
        "time": now.strftime("%H%M%S"),
        "datetime": now.strftime("%Y%m%d_%H%M%S"),
    }
    return re.sub(r"\{(\w+)\}", lambda m: tokens.get(m.group(1), m.group(0)), pattern)


def sanitize(name: str) -> str:
    n = _FORBIDDEN.sub("_", name or "").rstrip(" .")
    if not n.strip(" ."):
        return "Capture"
    if n.split(".")[0].upper() in _RESERVED:
        n = "_" + n
    return n[:MAX_LEN]


def normalize_ext(ext: str) -> str:
    e = ext.lower().lstrip(".")
    if e == "jpeg":
        e = "jpg"
    if e not in ("png", "jpg"):
        raise ValueError(f"unsupported image format: {ext!r}")
    return "." + e


def unique_path(directory, stem: str, ext: str, exists: Callable[[Path], bool] | None = None) -> Path:
    exists = exists or (lambda p: p.exists())
    d = Path(directory)
    base = sanitize(stem)
    e = normalize_ext(ext)
    # Windows refuses paths over 260 characters (without long-path support): shorten the name so
    # folder + name + "_123" + extension stays well inside
    room = PATH_LIMIT - len(str(d)) - 1 - len(e) - 6
    if len(base) > room:
        base = base[:max(MIN_STEM, room)].rstrip(" .") or "Capture"
    p = d / f"{base}{e}"
    i = 1
    while exists(p):
        p = d / f"{base}_{i}{e}"
        i += 1
    return p


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(p, os.W_OK)


def resolve_save_dir(configured, fallback, is_writable: Callable[[Path], bool] = _writable) -> tuple[Path, bool]:
    """Return (directory, used_fallback)."""
    if configured:
        c = Path(configured)
        if is_writable(c):
            return c, False
    f = Path(fallback)
    if is_writable(f):
        return f, True
    raise SaveDirError(f"저장할 수 있는 폴더가 없습니다: {configured!r}, {str(f)!r}")
