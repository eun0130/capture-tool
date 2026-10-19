"""Freeform (lasso) crop: keep only what is inside an outline the user drew.

The cut-out is BGRA: outside pixels are transparent *white*, so programs that ignore alpha
(JPG, many clipboard readers) show white instead of black."""
from __future__ import annotations

import cv2
import numpy as np

MIN_CLIP_AREA = 16   # px²; smaller outlines are a slip of the mouse, not a crop


def polygon(points, w: int, h: int) -> np.ndarray | None:
    """Outline clamped to the image as int32 points, or None if it encloses (almost) nothing."""
    if not points or len(points) < 3:
        return None
    pts = np.array([(min(max(x, 0), w - 1), min(max(y, 0), h - 1)) for x, y in points], np.float64)
    poly = np.round(pts).astype(np.int32)
    # enclosed area = filled pixels minus the outline itself (a straight line encloses nothing);
    # pixel counting also handles self-crossing outlines, whose signed area cancels out
    x, y, bw, bh = cv2.boundingRect(poly)
    local = poly - (x, y)
    filled = np.zeros((bh, bw), np.uint8)
    cv2.fillPoly(filled, [local], 1)
    edge = np.zeros_like(filled)
    cv2.polylines(edge, [local], True, 1)
    if int(filled.sum()) - int(edge.sum()) < MIN_CLIP_AREA:
        return None
    return poly


def _mask(poly: np.ndarray, h: int, w: int) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [poly], 255)
    return m


def _bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img[:, :, :3]


def clip_image(img: np.ndarray, points) -> np.ndarray | None:
    """BGRA cut-out, cropped to the outline's bounding box; None if the outline is too small."""
    h, w = img.shape[:2]
    poly = polygon(points, w, h)
    if poly is None:
        return None
    m = _mask(poly, h, w)
    x, y, bw, bh = cv2.boundingRect(poly)
    out = np.empty((bh, bw, 4), np.uint8)
    out[:, :, :3] = _bgr(img)[y:y + bh, x:x + bw]
    out[:, :, 3] = m[y:y + bh, x:x + bw]
    out[out[:, :, 3] == 0] = (255, 255, 255, 0)
    return out


def flatten(img: np.ndarray, bg: int = 255) -> np.ndarray:
    """BGRA -> BGR over a white background (for JPG and alpha-blind consumers)."""
    if img.ndim == 3 and img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255
        return (img[:, :, :3] * a + bg * (1 - a)).round().astype(np.uint8)
    return img


def mask_outside(img: np.ndarray, points) -> np.ndarray:
    """Same-size copy with everything outside the outline white (text/shape recognition)."""
    if points is None:
        return img
    h, w = img.shape[:2]
    poly = polygon(points, w, h)
    if poly is None:
        return img
    out = img.copy()
    out[_mask(poly, h, w) == 0] = 255
    return out
