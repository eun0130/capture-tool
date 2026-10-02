"""Tall test pages (like a scroll capture) with known text lines spread over the height."""
from __future__ import annotations

import numpy as np

from tests.render import render_text


def tall_page(height: int = 7000, width: int = 1200, every: int = 800, size: int = 22):
    img = np.full((height, width, 3), 255, np.uint8)
    want = []
    for i, y in enumerate(range(100, height - 150, every)):
        t = f"구간 {i} 매출 {1000 + i}"
        r = render_text([t], width=900, size=size)
        h, w = r.shape[:2]
        h = min(h, height - y)
        img[y:y + h, 50:50 + w] = r[:h, :, :3]
        want.append(t)
    return img, want
