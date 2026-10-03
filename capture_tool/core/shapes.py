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
MAX_COMPONENTS = 300    # a busy web page can hold thousands of blobs; keep the largest
TIME_BUDGET = 3.0       # seconds; never keep the CPU busy longer than this
SAME_COLOR = 30         # outline this close to the fill is just the fill's edge (no outline)
MAX_REREAD = 8          # coloured shapes whose missed text is read again (one OCR call each)
# common PowerPoint font sizes; a measured size snaps to the nearest
FONT_SIZES = (8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 44, 48, 54, 60, 66, 72, 80, 96)
BOLD_STROKE = 0.098     # stroke width / font size above this reads as bold (measured: 0.084 vs 0.113)


class _Budget:
    def __init__(self, seconds: float, count: int):
        import time
        self._now = time.perf_counter
        self.deadline = self._now() + seconds
        self.left = count

    def take(self) -> bool:
        if self.left <= 0 or self._now() > self.deadline:
            return False
        self.left -= 1
        return True


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
    text_color: str | None = None     # measured from the pixels (None: pick by contrast)
    font_size: float = 14             # points
    bold: bool = False


@dataclass
class TextStyle:
    color: str = "#000000"
    size: float = 14
    bold: bool = False


def _em_factor(text: str) -> float:
    """Ink height of a line as a share of its font size: Hangul/CJK fill the em box; Latin
    depends on capitals/ascenders and descenders."""
    if any("\uac00" <= c <= "\ud7a3" or "\u3040" <= c <= "\u9fff" for c in text):
        return 0.95
    asc = any(c.isupper() or c.isdigit() or c in "bdfhklt'\"([{/|" for c in text)
    desc = any(c in "gjpqy,;()[]{}|" for c in text)
    return (0.72 if asc else 0.53) + (0.28 if desc else 0.0)


def _snap(size: float) -> float:
    return min(FONT_SIZES, key=lambda v: abs(v - size))


def text_style(img: np.ndarray, box, text: str, dpi: float = 96) -> TextStyle:
    """Colour, size (pt) and boldness of the text inside an OCR box, read from its pixels."""
    img = _to_bgr(img)
    x, y, w, h = (int(round(v)) for v in box)
    x0, y0 = max(0, x), max(0, y)
    c = img[y0:max(y0, y + h), x0:max(x0, x + w)].astype(np.int16)
    if c.shape[0] < 3 or c.shape[1] < 3:
        return TextStyle()
    bg = np.median(np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]]), axis=0)
    d = np.abs(c - bg).max(axis=2)
    m = d > max(40, int(d.max() * 0.5))
    if m.sum() < 6:
        return TextStyle()
    strong = c[d >= np.percentile(d[m], 70)]
    col = np.median(strong, axis=0)
    rows = np.where(m.any(axis=1))[0]
    ink_h = rows[-1] - rows[0] + 1
    em_px = ink_h / _em_factor(text)
    mk = m.astype(np.uint8)
    contours, _ = cv2.findContours(mk, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    per = sum(cv2.arcLength(k, True) for k in contours)
    stroke = 2 * float(mk.sum()) / max(per, 1.0)
    return TextStyle(_hex(col), _snap(em_px * 72 / dpi), stroke / max(em_px, 1.0) > BOLD_STROKE)


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
    _detect_in(img, region, _background(img), out, depth=0, budget=_Budget(TIME_BUDGET, MAX_COMPONENTS))
    out = _dedupe(out)[:MAX_COMPONENTS]
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


def _detect_in(img, region, bg, out, depth, budget: _Budget):
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

    regions = []
    for i, c in enumerate(contours):
        if level(i) % 2:          # hole boundary, not a region
            continue
        area = cv2.contourArea(c)
        if area < MIN_AREA and cv2.arcLength(c, True) < 60:
            continue
        regions.append((area, i, c))
    regions.sort(key=lambda r: -r[0])  # largest first, so a budget cut drops only small noise
    for _, i, c in regions:
        if not budget.take():
            return
        has_hole = hier[i][2] >= 0
        split = _split_attached_lines(img, c, fg)
        if split is not None:
            bodies, lines = split
            out.extend(lines)
            candidates = [(b, True) for b in bodies]
        else:
            candidates = [(c, has_hole)]
        for contour, hole in candidates:
            d = _classify(img, contour, fg, hole, bg)
            if d is None:
                continue
            out.append(d)
            if d.fill and depth < 3 and d.kind not in ("line", "arrow"):
                _recurse(img, contour, d, region, out, depth, budget)


SPLIT_KERNEL = 13  # px; shape bodies are thicker than this, connector lines are thinner


def _split_attached_lines(img, contour, fg):
    """A connector touching a shape merges with it into one region. Cut off the thin
    parts that look like lines/arrows and return (shape body contours, line detections)."""
    x, y, w, h = cv2.boundingRect(contour)
    if w < 30 and h < 30:
        return None
    p = 2
    m = np.zeros((h + 2 * p, w + 2 * p), np.uint8)
    cv2.drawContours(m, [contour - [x - p, y - p]], -1, 255, -1)
    opened = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((SPLIT_KERNEL, SPLIT_KERNEL), np.uint8))
    if np.count_nonzero(opened) < 0.3 * np.count_nonzero(m):
        return None  # mostly thin: the whole region is a line, handled by _classify
    thin = cv2.bitwise_and(m, cv2.bitwise_not(cv2.dilate(opened, np.ones((5, 5), np.uint8))))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(thin)
    lines, remove = [], np.zeros_like(m)
    for j in range(1, n):
        if stats[j, cv2.CC_STAT_AREA] < 25:
            continue
        ys, xs = np.nonzero(labels == j)
        gx, gy = xs + x - p, ys + y - p
        keep = fg[gy, gx] > 0
        if keep.sum() < 10:
            continue
        pts = np.stack([gx[keep], gy[keep]], axis=1)
        d = _line_from_points(img, pts)
        if d is not None:
            lines.append(d)
            remove[labels == j] = 255
    if not lines:
        return None
    body = cv2.bitwise_and(m, cv2.bitwise_not(cv2.dilate(remove, np.ones((3, 3), np.uint8))))
    body = cv2.morphologyEx(body, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cs, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    bodies = [cc + [x - p, y - p] for cc in cs if cv2.contourArea(cc) >= MIN_AREA]
    return bodies, lines


def _recurse(img, contour, d, region, out, depth, budget: _Budget):
    """Look for nested shapes inside a filled shape, using its fill as background.
    Works on the shape's bounding box only (not the whole screenshot)."""
    pad = 14  # margin so erosion treats the outside of the shape as outside
    x0, y0, w0, h0 = cv2.boundingRect(contour)
    x, y = max(0, x0 - pad), max(0, y0 - pad)
    ex, ey = min(img.shape[1], x0 + w0 + pad), min(img.shape[0], y0 + h0 + pad)
    sub = img[y:ey, x:ex]
    filled = np.zeros((ey - y, ex - x), np.uint8)
    cv2.drawContours(filled, [contour - [x, y]], -1, 255, -1)
    k = int(d.stroke_width) * 2 + 5
    inner = cv2.erode(filled, np.ones((k, k), np.uint8))
    inner = cv2.bitwise_and(inner, region[y:ey, x:ex])
    fill_bgr = _parse(d.fill)
    if np.count_nonzero((_dist(sub, fill_bgr) > FG_THRESHOLD) & (inner > 0)) < MIN_AREA:
        return
    nested: list[Detected] = []
    _detect_in(sub, inner, fill_bgr, nested, depth + 1, budget)
    for n in nested:
        n.x += x
        n.y += y
        n.points = [(px + x, py + y) for px, py in n.points]
    out.extend(nested)


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
    return _line_from_points(img, np.stack([xs + x, ys + y], axis=1))


def _line_from_points(img, pts: np.ndarray) -> Detected | None:
    """Pixels of one region -> line/arrow if the region is a thin straight stroke."""
    if len(pts) < 10:
        return None
    x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
    w, h = int(pts[:, 0].max()) - x + 1, int(pts[:, 1].max()) - y + 1
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
    px = img[pts[:, 1], pts[:, 0]]  # sample the stroke pixels directly (no full-screen mask)
    color = tuple(int(v) for v in np.median(px, axis=0)) if len(px) else None
    d = Detected("arrow" if is_arrow else "line", x, y, w, h,
                 fill=None, stroke=_hex(color) if color else None, stroke_width=float(max(1, round(body - 1))),
                 points=[(int(round(start[0])), int(round(start[1]))), (int(round(end[0])), int(round(end[1])))])
    return d


def _is_diamond(approx, x, y, w, h) -> bool:
    """Four corners sitting on the middles of the bounding box's sides."""
    mids = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    tol = 0.12 * max(w, h)
    pts = [tuple(p[0]) for p in approx]
    return all(min(abs(px - mx) + abs(py - my) for px, py in pts) <= tol for mx, my in mids)


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
    elif len(approx) == 4 and 0.42 <= extent <= 0.62 and _is_diamond(approx, x, y, w, h):
        kind = "diamond"
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
    # work on the shape's bounding box (+margin so erosion sees the outside), not the whole screenshot
    pad = 14
    x0, y0, w0, h0 = cv2.boundingRect(contour)
    bx, by = max(0, x0 - pad), max(0, y0 - pad)
    ex, ey = min(img.shape[1], x0 + w0 + pad), min(img.shape[0], y0 + h0 + pad)
    img = img[by:ey, bx:ex]
    filled = np.zeros((ey - by, ex - bx), np.uint8)
    cv2.drawContours(filled, [contour - [bx, by]], -1, 255, -1)
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
        if stroke is not None and max(abs(a - b) for a, b in zip(fill, stroke)) <= SAME_COLOR:
            d.stroke = None                          # a plain fill: its edge is not an outline
    return d


# --- PowerPoint mapping -------------------------------------------------------

def attach_text(shapes: list[Detected], lines: list[tuple[str, tuple]], img=None,
                dpi: float = 96) -> list[tuple[str, tuple]]:
    """Put each OCR line into the smallest closed shape containing its center; with the image,
    the shape also takes the text's colour, size and boldness (from its biggest line).
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
        buckets.setdefault(best, []).append((y, x, text, (x, y, w, h)))
    for i, items in buckets.items():
        shapes[i].text = "\n".join(t for _, _, t, _ in sorted(items))
        if img is not None:
            big = max((it for it in items), key=lambda it: it[3][3])
            st = text_style(img, big[3], big[2], dpi)
            shapes[i].text_color, shapes[i].font_size, shapes[i].bold = st.color, st.size, st.bold
    return rest


def _near_color(a: str, b: str, tol: int = 60) -> bool:
    return max(abs(int(a[k:k + 2], 16) - int(b[k:k + 2], 16)) for k in (1, 3, 5)) <= tol


def text_boxes_for(lines: list[tuple[str, tuple]], img, dpi: float = 96) -> list[Detected]:
    """Text outside every shape -> free text boxes keeping colour, size and boldness; lines of
    one paragraph (same left edge, same look, close together) stay in one box."""
    items = []
    for text, box in sorted(lines, key=lambda l: (l[1][1], l[1][0])):
        if text and text.strip():
            items.append((text.strip(), box, text_style(img, box, text, dpi)))
    groups: list[list] = []
    for it in items:
        _, (x, y, w, h), st = it
        g = groups[-1] if groups else None
        if g:
            _, (gx, gy, gw, gh), gst = g[-1]
            if (abs(x - g[0][1][0]) <= 0.6 * h and 0.75 <= h / max(gh, 1) <= 1.33
                    and 0 <= y - (gy + gh) <= 0.9 * h and gst.size == st.size and gst.bold == st.bold
                    and _near_color(gst.color, st.color)):
                g.append(it)
                continue
        groups.append([it])
    pad_x, pad_y = 0.1 * dpi, 0.05 * dpi                 # PowerPoint's text box insets
    out = []
    for g in groups:
        x1 = min(b[0] for _, b, _ in g)
        y1 = min(b[1] for _, b, _ in g)
        x2 = max(b[0] + b[2] for _, b, _ in g)
        y2 = max(b[1] + b[3] for _, b, _ in g)
        st = g[0][2]
        out.append(Detected("text", int(x1 - pad_x), int(y1 - pad_y), int(x2 - x1 + 2 * pad_x),
                            int(y2 - y1 + 2 * pad_y), text="\n".join(t for t, _, _ in g),
                            text_color=st.color, font_size=st.size, bold=st.bold))
    return out


def find_missed_text(img, detected: list[Detected], recognize) -> list[tuple[str, tuple]]:
    """A coloured shape with ink inside but no text: OCR on the whole screen can miss it (dark
    text on a saturated fill), so read just that shape again. Bits of those letters that were
    taken for tiny shapes are removed from `detected`. Returns the new (text, box) lines in
    whole-image coordinates. recognize(crop) -> [(text, (x, y, w, h)), ...]."""
    img = _to_bgr(img)
    found: list[tuple[str, tuple]] = []
    tries = 0
    for d in sorted(detected, key=lambda d: -d.w * d.h):
        if tries >= MAX_REREAD:
            break
        if d.kind in ("line", "arrow", "text") or d.text or not d.fill or d.w < 30 or d.h < 20:
            continue
        ix, iy = d.x + d.w // 5, d.y + d.h // 5
        inner = img[iy:iy + max(1, d.h * 3 // 5), ix:ix + max(1, d.w * 3 // 5)]
        if inner.size == 0:
            continue
        fill = tuple(int(d.fill[k:k + 2], 16) for k in (5, 3, 1))
        if (_dist(inner, fill) > 60).mean() < 0.01:
            continue                                    # nothing written inside
        tries += 1
        crop = img[d.y:d.y + d.h, d.x:d.x + d.w]
        for text, (x, y, w, h) in recognize(crop) or []:
            if text and text.strip():
                found.append((text, (d.x + x, d.y + y, w, h)))
    if found:
        def inside_text(o: Detected) -> bool:
            cx, cy = o.x + o.w / 2, o.y + o.h / 2
            return any(x - 2 <= cx <= x + w + 2 and y - 2 <= cy <= y + h + 2 and o.w * o.h < w * h * 1.5
                       for _, (x, y, w, h) in found)
        detected[:] = [o for o in detected if not inside_text(o)]
    return found


def _edge_distance(p, s: Detected) -> float:
    dx = max(s.x - p[0], 0, p[0] - (s.x + s.w))
    dy = max(s.y - p[1], 0, p[1] - (s.y + s.h))
    return (dx * dx + dy * dy) ** 0.5


def to_drawing(detected: list[Detected]) -> tuple[list[DShape], list[DConnector]]:
    closed = [d for d in detected if d.kind not in ("line", "arrow")]

    def color(d: Detected) -> str:
        return d.text_color or ("#000000" if not d.fill else _text_color(d.fill))

    shapes = []
    for d in closed:
        if d.kind == "text":
            shapes.append(DShape("rect", d.x, d.y, d.w, d.h, fill=None, stroke=None, text=d.text,
                                 text_color=color(d), font_size=d.font_size, bold=d.bold, wrap=False, align="l"))
        else:
            stroke = d.stroke if (d.stroke or d.fill) else "#000000"
            shapes.append(DShape(d.kind, d.x, d.y, d.w, d.h, fill=d.fill, stroke=stroke,
                                 stroke_width=d.stroke_width, text=d.text, text_color=color(d),
                                 font_size=d.font_size, bold=d.bold))
    conns = []
    for d in detected:
        if d.kind not in ("line", "arrow"):
            continue
        (x1, y1), (x2, y2) = d.points

        def near(p):
            best = None
            for i, s in enumerate(closed):
                if s.kind == "text":
                    continue                            # arrows point at shapes, not at labels
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


def attach_found_text(img, detected: list[Detected], lines: list[tuple[str, tuple]], recognize,
                      dpi: float = 96) -> list[tuple[str, tuple]]:
    """OCR lines into their shapes (with style), then a second look only inside coloured
    shapes that are still empty. Returns the lines outside every shape."""
    rest = attach_text(detected, lines, img=img, dpi=dpi)
    extra = find_missed_text(img, detected, recognize)
    if extra:
        rest += attach_text(detected, extra, img=img, dpi=dpi)
    return rest


SURE_OCR = 0.8          # OCR lines below this score may be half-read words with oversized boxes


def split_doubtful(lines) -> tuple[list[tuple], list[tuple[str, tuple]]]:
    """lines: (text, box, score). Returns (boxes to hide from the shape search - sure lines only,
    since a doubtful box can cover and cut a whole shape -, all lines as (text, box))."""
    return [b for _, b, sc in lines if sc >= SURE_OCR], [(t, b) for t, b, _ in lines]


def drop_doubtful_inside(detected: list[Detected], lines) -> list[tuple[str, tuple]]:
    """(text, box) of the lines to use: a doubtful line inside a coloured shape is left out so
    that shape is read again on its own."""
    filled = [d for d in detected if d.kind not in ("line", "arrow", "text") and d.fill]
    out = []
    for text, (x, y, w, h), sc in lines:
        cx, cy = x + w / 2, y + h / 2
        if sc < SURE_OCR and any(d.x <= cx <= d.x + d.w and d.y <= cy <= d.y + d.h for d in filled):
            continue
        out.append((text, (x, y, w, h)))
    return out
