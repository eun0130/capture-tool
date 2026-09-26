"""Color parsing, pixel sampling and recent-color list."""
from __future__ import annotations

import re

import numpy as np

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex(value) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid color: {value!r}")
    m = _HEX.match(value.strip())
    if not m:
        raise ValueError(f"invalid color: {value!r}")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = normalize_hex(value)
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def rgb_string(value: str) -> str:
    r, g, b = hex_to_rgb(value)
    return f"RGB {r},{g},{b}"


def pixel_color(img: np.ndarray, x: int, y: int) -> str | None:
    """Color at (x, y) of a BGR / BGRA / grayscale image, or None if outside."""
    h, w = img.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return None
    px = img[y, x]
    if img.ndim == 2:
        v = int(px)
        return rgb_to_hex(v, v, v)
    b, g, r = (int(c) for c in px[:3])
    return rgb_to_hex(r, g, b)


def push_recent(recent: list[str], color: str, limit: int = 8) -> list[str]:
    c = normalize_hex(color)
    return ([c] + [x for x in recent if x != c])[:limit]
