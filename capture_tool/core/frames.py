"""The still picture behind the capture screen. On Windows two ways read the screen: DXGI desktop
duplication sees exactly what the monitor shows; the old GDI grab misses windows drawn straight by the
GPU (flip-model swap chains) and gives white or black there - Windows Terminal running herdr came out
all white (BUG-142). DXGI is preferred; GDI stays the fallback (remote desktop, old drivers)."""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from .geometry import Rect
from .scroll_session import looks_blocked

log = logging.getLogger("capture_tool")


def still_frame(r: Rect, dxgi: Callable[[Rect], np.ndarray | None],
                gdi: Callable[[Rect], np.ndarray]) -> np.ndarray:
    """BGRA picture of `r`: the DXGI one when it has a picture of the right size, else the GDI one. A
    DXGI picture of one flat color (a secure screen, a failed copy) only wins when GDI's is flat too."""
    try:
        dx = dxgi(r)
    except Exception as e:  # noqa: BLE001 - any DXGI failure: the old way
        log.info("DXGI capture unavailable (%s) - GDI grab", e)
        dx = None
    if dx is not None and dx.shape[:2] != (r.h, r.w):
        dx = None
    if dx is not None and not looks_blocked(dx):
        return dx
    old = gdi(r)
    if dx is not None and looks_blocked(old):
        return dx
    return old
