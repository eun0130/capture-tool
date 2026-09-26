"""Recognize diagram shapes in a screenshot (OpenCV), then map them to PowerPoint shapes.

Pipeline: background color -> foreground mask (minus OCR text boxes) -> connected
regions via contour tree -> classify each region (line/arrow by thickness profile,
closed shapes by polygon/extent/corner tests) -> colors -> recurse inside filled
shapes to find nested shapes."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .color import rgb_to_hex
from .drawingml import DConnector, DShape

FG_THRESHOLD = 48       # color distance from background that counts as foreground
MIN_AREA = 120          # px; smaller regions are noise
MAX_LINE_THICK = 10     # px; median thickness of a line/arrow body
LINK_DISTANCE = 14      # px; arrow endpoint to shape edge to count as connected


@dataclass
class Detected:
    kind: str
    x: int
    y: int
    w: int
    h: int
    fill: str | None = None
    stroke: str | None = None
    stroke_width: float = 2
    points: list = field(default_factory=list)
    text: str | None = None


def _to_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def _dist(img: np.ndarray, color) -> np.ndarray:
    return np.abs(img.astype(np.int16) - np.array(color, np.int16)).max(axis=2)


def _median_color(img: np.ndarray, mask: np.ndarray):
    px = img[mask > 0]
    if len(px) == 0:
        return None
    return tuple(int(v) for v in np.median(px, axis=0))


def _hex(bgr) -> str:
    return rgb_to_hex(bgr[2], bgr[1], bgr[0])


def _background(img: np.ndarray):
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    return tuple(int(v) for v in np.median(border, axis=0))


def detect(img: np.ndarray, text_boxes=None) -> list[Detected]:
    if img is None or img.size == 0 or min(img.shape[:2]) < 8:
        return []
    img = _to_bgr(img)
    region = np.full(img.shape[:2], 255, np.uint8)
    for (x, y, w, h) in text_boxes or []:
        region[max(0, int(y)):int(y + h), max(0, int(x)):int(x + w)] = 0
    out: list[Detected] = []
    _detect_in(img, region, _background(img), out, depth=0)
    out = _dedupe(out)
    out.sort(key=lambda d: (d.y, d.x))
    return out


def _iou(a: Detected, b: Detected) -> float:
    iw = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    ih = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    inter = iw * ih
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def _dedupe(found: list[Detected]) -> list[Detected]:
    """A light-filled shape can be found both at top level and again while recursing."""
    keep: list[Detected] = []
    for d in found:
        if any(k.kind == d.kind and _iou(k, d) > 0.85 for k in keep):
            continue
        keep.append(d)
    return keep


def _detect_in(img, region, bg, out, depth):
    fg = ((_dist(img, bg) > FG_THRESHOLD) & (region > 0)).astype(np.uint8) * 255
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, hier = cv2.findContours(fg, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return
    hier = hier[0]

    def level(i):
        n = 0
        while hier[i][3] >= 0:
            i = hier[i][3]
            n += 1
        return n

    for i, c in enumerate(contours):
        if level(i) % 2:          # hole boundary, not a region
            continue
        if cv2.contourArea(c) < MIN_AREA and cv2.arcLength(c, True) < 60:
            continue
        has_hole = hier[i][2] >= 0
        d = _classify(img, c, fg, has_hole, bg)
        if d is None:
            continue
        out.append(d)
        if d.fill and depth < 3 and d.kind not in ("line", "arrow"):
            _recurse(img, c, d, region, out, depth)


def _recurse(img, contour, d, region, out, depth):
    """Look for nested shapes inside a filled shape, using its fill as background."""
    filled = np.zeros(img.shape[:2], np.uint8)
    cv2.drawContours(filled, [contour], -1, 255, -1)
    k = int(d.stroke_width) * 2 + 5
    inner = cv2.erode(filled, np.ones((k, k), np.uint8))
    inner = cv2.bitwise_and(inner, region)
    fill_bgr = _parse(d.fill)
    if np.count_nonzero((_dist(img, fill_bgr) > FG_THRESHOLD) & (inner > 0)) < MIN_AREA:
        return
    _detect_in(img, inner, fill_bgr, out, depth + 1)


def _parse(hex_color):
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


# --- classification ----------------------------------------------------------

def _line_profile(mask_pts: np.ndarray):
    """PCA axis of pixel cloud -> (center, axis, t-coords, thickness per bin)."""
    pts = mask_pts.astype(np.float64)
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T)
    vals, vecs = np.linalg.eigh(cov)
    axis = vecs[:, np.argmax(vals)]
    perp = np.array([-axis[1], axis[0]])
    t = (pts - mean) @ axis
    s = (pts - mean) @ perp
    return mean, axis, t, s


def _try_line(img, contour, fg, bg):
    x, y, w, h = cv2.boundingRect(contour)
    blob = np.zeros((h, w), np.uint8)
    cv2.drawContours(blob, [contour - [x, y]], -1, 255, -1, offset=(0, 0))
    blob &= fg[y:y + h, x:x + w]
    ys, xs = np.nonzero(blob)
    if len(xs) < 10:
        return None
    pts = np.stack([xs + x, ys + y], axis=1)
    mean, axis, t, s = _line_profile(pts)
    length = t.max() - t.min()
    if length < 20:
        return None
    nbins = max(8, int(length // 4))
    edges = np.linspace(t.min(), t.max() + 1e-6, nbins + 1)
    idx = np.clip(np.digitize(t, edges) - 1, 0, nbins - 1)
    thick = np.zeros(nbins)
    for b in range(nbins):
        sel = s[idx == b]
        if len(sel):
            thick[b] = sel.max() - sel.min() + 1
    body = np.median(thick[thick > 0])
    if body > MAX_LINE_THICK or length < 4 * body:
        return None
    # the body must be straight: thickness mostly ~body
    straight = np.mean(thick <= body * 1.8 + 1)
    if straight < 0.6:
        return None
    k = max(2, nbins // 7)
    head_a, head_b = thick[:k].max(), thick[-k:].max()
    is_arrow = max(head_a, head_b) >= body * 2.2 + 2
    p_min = mean + axis * t.min()
    p_max = mean + axis * t.max()
    start, end = p_min, p_max
    if is_arrow and head_a > head_b:
        start, end = p_max, p_min
    color = _median_color(img, _full_mask(img, pts))
    d = Detected("arrow" if is_arrow else "line", x, y, w, h,
                 fill=None, stroke=_hex(color) if color else None, stroke_width=float(max(1, round(body - 1))),
                 points=[(int(round(start[0])), int(round(start[1]))), (int(round(end[0])), int(round(end[1])))])
    return d


def _full_mask(img, pts):
    m = np.zeros(img.shape[:2], np.uint8)
    m[pts[:, 1], pts[:, 0]] = 255
    # core pixels only (avoid anti-aliased edge)
    return m


def _corner_gap(contour, x, y, w, h) -> float:
    pts = contour.reshape(-1, 2).astype(np.float64)
    gaps = []
    for cx, cy in [(x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)]:
        gaps.append(np.min(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)))
    return float(np.median(gaps))


def _classify(img, contour, fg, has_hole, bg) -> Detected | None:
    if not has_hole:
        d = _try_line(img, contour, fg, bg)
        if d is not None:
            return d
    x, y, w, h = cv2.boundingRect(contour)
    if w < 8 or h < 8:
        return None
    area = cv2.contourArea(contour)
    extent = area / float(w * h)
    hull_area = cv2.contourArea(cv2.convexHull(contour))
    solidity = area / hull_area if hull_area else 0
    if solidity < 0.9:
        return None
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.03 * peri, True)
    kind = None
    if len(approx) == 3 and 0.4 <= extent <= 0.62:
        kind = "triangle"
    elif (extent >= 0.965 or (len(approx) == 4 and extent >= 0.93)) and _corner_gap(contour, x, y, w, h) < 2.5:
        kind = "rect"
        if len(approx) == 4:  # ignore small bumps (noise touching the edge)
            ax, ay, aw, ah = cv2.boundingRect(approx)
            if aw * ah >= 0.9 * w * h:
                x, y, w, h = ax, ay, aw + 1, ah + 1
    elif 0.74 <= extent <= 0.83:
        (ecx, ecy), (ea, eb), _ = cv2.fitEllipse(contour) if len(contour) >= 5 else ((0, 0), (0, 0), 0)
        if abs(ea * eb * np.pi / 4 - area) / max(area, 1) < 0.08:
            kind = "ellipse"
    if kind is None and 0.83 < extent < 0.995:
        if _corner_gap(contour, x, y, w, h) >= 2.5:
            kind = "roundRect"
    if kind is None and extent >= 0.965:
        kind = "rect"
    if kind is None:
        return None
    return _colors(img, contour, bg, Detected(kind, x, y, w, h))


def _colors(img, contour, bg, d: Detected) -> Detected:
    filled = np.zeros(img.shape[:2], np.uint8)
    cv2.drawContours(filled, [contour], -1, 255, -1)
    # stroke: thin band just inside the edge, skipping the anti-aliased outermost pixel
    e1 = cv2.erode(filled, np.ones((3, 3), np.uint8))
    e2 = cv2.erode(filled, np.ones((5, 5), np.uint8))
    stroke = _median_color(img, cv2.subtract(e1, e2))
    # measure stroke thickness: how far from the edge pixels stay close to stroke color
    width = 1
    prev = e1
    for k in range(2, 12):
        ek = cv2.erode(filled, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
        band = cv2.subtract(prev, ek)
        c = _median_color(img, band)
        if c is None or stroke is None or max(abs(a - b) for a, b in zip(c, stroke)) > 40:
            break
        width = k
        prev = ek
    k = width * 2 + 5
    inner = cv2.erode(filled, np.ones((k, k), np.uint8))
    fill = _median_color(img, inner)
    d.stroke = _hex(stroke) if stroke else None
    d.stroke_width = float(width)
    if fill is None or max(abs(a - b) for a, b in zip(fill, bg)) <= 12:
        d.fill = None
    else:
        d.fill = _hex(fill)
    return d


# --- PowerPoint mapping -------------------------------------------------------

def attach_text(shapes: list[Detected], lines: list[tuple[str, tuple]]) -> list[tuple[str, tuple]]:
    """Put each OCR line into the smallest closed shape containing its center.
    Returns the lines that fall outside every shape."""
    rest = []
    buckets: dict[int, list] = {}
    closed = [i for i, s in enumerate(shapes) if s.kind not in ("line", "arrow")]
    for text, (x, y, w, h) in lines:
        cx, cy = x + w / 2, y + h / 2
        inside = [i for i in closed if shapes[i].x <= cx <= shapes[i].x + shapes[i].w
                  and shapes[i].y <= cy <= shapes[i].y + shapes[i].h]
        if not inside:
            rest.append((text, (x, y, w, h)))
            continue
        best = min(inside, key=lambda i: shapes[i].w * shapes[i].h)
        buckets.setdefault(best, []).append((y, x, text))
    for i, items in buckets.items():
        shapes[i].text = "\n".join(t for _, _, t in sorted(items))
    return rest


def _edge_distance(p, s: Detected) -> float:
    dx = max(s.x - p[0], 0, p[0] - (s.x + s.w))
    dy = max(s.y - p[1], 0, p[1] - (s.y + s.h))
    return (dx * dx + dy * dy) ** 0.5


def to_drawing(detected: list[Detected]) -> tuple[list[DShape], list[DConnector]]:
    closed = [d for d in detected if d.kind not in ("line", "arrow")]
    shapes = [DShape(d.kind, d.x, d.y, d.w, d.h, fill=d.fill, stroke=d.stroke or "#000000",
                     stroke_width=d.stroke_width, text=d.text,
                     text_color="#000000" if not d.fill else _text_color(d.fill)) for d in closed]
    conns = []
    for d in detected:
        if d.kind not in ("line", "arrow"):
            continue
        (x1, y1), (x2, y2) = d.points

        def near(p):
            best = None
            for i, s in enumerate(closed):
                dist = _edge_distance(p, s)
                if dist <= LINK_DISTANCE and (best is None or dist < best[0]):
                    best = (dist, i)
            return best[1] if best else None

        a, b = near((x1, y1)), near((x2, y2))
        linked = a is not None and b is not None and a != b
        conns.append(DConnector(start=a if linked else None, end=b if linked else None,
                                x1=x1, y1=y1, x2=x2, y2=y2, color=d.stroke or "#000000",
                                width=d.stroke_width, arrow=d.kind == "arrow"))
    return shapes, conns


def _text_color(fill_hex: str) -> str:
    r, g, b = int(fill_hex[1:3], 16), int(fill_hex[3:5], 16), int(fill_hex[5:7], 16)
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#FFFFFF"
