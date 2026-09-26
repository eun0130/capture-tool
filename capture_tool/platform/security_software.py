"""Detect corporate DRM agents that inject DLLs into every process.

Why: Fasoo DRM injects f_nxa.dll into Office processes. Office's local AI host (ai.exe,
started by PowerPoint/OneNote a few seconds after launch) only accepts Microsoft-signed
DLLs, so Windows shows "ai.exe - Bad Image ... f_nxa.dll ... 0xc0000428". The dialog is
harmless for PowerPoint and this app, but users think the capture tool broke something."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Callable

# (product name, DLL injected into processes, install folder under Program Files)
KNOWN = [
    ("Fasoo DRM", "f_nxa.dll", "Fasoo DRM"),
]


def _module_loaded(name: str) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    return bool(k32.GetModuleHandleW(name))


def _program_dirs() -> list[Path]:
    dirs = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(var)
        if v and Path(v) not in dirs:
            dirs.append(Path(v))
    return dirs


def detect_drm(module_loaded: Callable[[str], bool] | None = None,
               path_exists: Callable[[Path], bool] | None = None) -> str | None:
    """Name of a detected DRM agent, or None. Never raises."""
    module_loaded = module_loaded or _module_loaded
    path_exists = path_exists or (lambda p: p.exists())
    for product, dll, folder in KNOWN:
        try:
            if module_loaded(dll):
                return product
        except Exception:  # noqa: BLE001 - detection is best effort
            pass
        for base in _program_dirs() or [Path("C:/Program Files")]:
            try:
                if path_exists(base / folder):
                    return product
            except Exception:  # noqa: BLE001
                pass
    return None
