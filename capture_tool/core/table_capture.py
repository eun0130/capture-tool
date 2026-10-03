"""A table inside a capture (light or dark page, with or without ruling lines) -> rows of
cells plus its look (header/body fill, text colours, border, font size, column widths), so it
can go to PowerPoint as a real table instead of loose text boxes."""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

import numpy as np

from .shapes import _dist, _hex, _to_bgr, text_style
from .table import _bands, _rows, to_grid

MIN_ROWS = 3
MIN_COLS = 2
MAX_ROWS = 200
MAX_COLS = 20
MIN_FILL = 0.6            # share of cells holding text
MIN_MULTI = 0.6           # share of rows with two or more cells
MAX_SPACING_CV = 0.35     # rows of a table are evenly spaced
DIAGRAM_SHARE = 0.02      # a closed shape this big (of the image) means a diagram, not a table


@dataclass
class TableStyle:
    header_fill: str
    body_fill: str
    header_text: str
    body_text: str
    border: str | None
    header_bold: bool
    font_size: float


@dataclass
class CapturedTable:
    rows: list[list[str]]
    box: tuple                                  # x, y, w, h in image pixels
    outside: list[tuple[str, tuple]] = field(default_factory=list)   # titles / notes around it
    style: TableStyle | None = None
    col_widths: list[float] = field(default_factory=list)            # points


def _median_color(img, mask):
    px = img[mask]
    return None if len(px) == 0 else tuple(int(v) for v in np.median(px, axis=0))


def find_table(img, lines, shapes, dpi: float = 96) -> CapturedTable | None:
    """lines: (text, (x, y, w, h), score); shapes: Detected from the shape search."""
    if img is None or img.size == 0:
        return None
    img = _to_bgr(img)
    H, W = img.shape[:2]
    for s in shapes or []:
        if s.kind not in ("line", "arrow", "text") and s.w * s.h >= DIAGRAM_SHARE * W * H:
            return None
    items = [(t.strip(), *b) for t, b, _ in lines if t and t.strip()]
    if len(items) < MIN_ROWS * MIN_COLS:
        return None
    h = median(i[4] for i in items)
    rows = _rows(items, tol=h * 0.5)
    outside: list[tuple[str, tuple]] = []
    while len(rows) > MIN_ROWS and len(rows[0]) == 1:
        outside.extend((i[0], tuple(i[1:])) for i in rows.pop(0))
    while len(rows) > MIN_ROWS and len(rows[-1]) == 1:
        outside.extend((i[0], tuple(i[1:])) for i in rows.pop())
    if len(rows) < MIN_ROWS or len(rows) > MAX_ROWS:
        return None
    if sum(len(r) >= 2 for r in rows) < MIN_MULTI * len(rows):
        return None
    centers = [median(i[2] + i[4] / 2 for i in r) for r in rows]
    gaps = [b - a for a, b in zip(centers, centers[1:])]
    if np.std(gaps) > MAX_SPACING_CV * np.mean(gaps):
        return None
    table_items = [i for r in rows for i in r]
    grid = to_grid(table_items)
    if not grid or len(grid) < MIN_ROWS or not (MIN_COLS <= len(grid[0]) <= MAX_COLS):
        return None
    cells = len(grid) * len(grid[0])
    if sum(1 for r in grid for c in r if c) < MIN_FILL * cells:
        return None

    gap = float(np.mean(gaps))
    x1 = min(i[1] for i in table_items)
    x2 = max(i[1] + i[3] for i in table_items)
    y1 = int(max(0, centers[0] - gap / 2))
    y2 = int(min(H, centers[-1] + gap / 2))
    style = _style(img, rows, centers, gap, table_items, x1, x2, y1, y2, dpi)
    # the table's own edges: where the header fill (if it differs from the page) runs out
    page = tuple(int(v) for v in np.median(np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]]), axis=0))
    hf = tuple(int(style.header_fill[k:k + 2], 16) for k in (5, 3, 1))
    if max(abs(a - b) for a, b in zip(hf, page)) > 10:
        row = img[int(centers[0])]
        on = np.where(_dist(row[None], hf)[0] <= 12)[0]
        if len(on):
            x1, x2 = min(x1, int(on.min())), max(x2, int(on.max()) + 1)
    pad = int(h * 0.4)
    bx1, bx2 = max(0, x1 - pad), min(W, x2 + pad)
    starts = [b[0] for b in _bands(rows)]
    if len(starts) == len(grid[0]):
        lefts = [bx1] + [s - pad for s in starts[1:]]
        widths = [max(1.0, b - a) for a, b in zip(lefts, lefts[1:] + [bx2])]
    else:
        widths = [(bx2 - bx1) / len(grid[0])] * len(grid[0])
    return CapturedTable(grid, (bx1, y1, bx2 - bx1, y2 - y1), outside, style, [w * 72 / dpi for w in widths])


def _style(img, rows, centers, gap, items, x1, x2, y1, y2, dpi) -> TableStyle:
    H, W = img.shape[:2]
    text_mask = np.zeros((H, W), bool)
    for _, x, y, w, h in items:
        text_mask[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2] = True
    bounds = [y1] + [int((a + b) / 2) for a, b in zip(centers, centers[1:])] + [y2]
    xs = slice(max(0, x1), min(W, x2))

    def band_fill(top, bottom):
        m = np.zeros((H, W), bool)
        m[top + 3:max(top + 4, bottom - 3), xs] = True
        return _median_color(img, m & ~text_mask)

    header = band_fill(bounds[0], bounds[1]) or (255, 255, 255)
    body_px = np.zeros((H, W), bool)
    for top, bottom in zip(bounds[1:-1], bounds[2:]):
        body_px[top + 3:max(top + 4, bottom - 3), xs] = True
    body = _median_color(img, body_px & ~text_mask) or (255, 255, 255)
    # border: the row line between body rows that stands out most from the body fill
    border = None
    best = 0
    for b in bounds[2:-1][:6]:
        for y in range(max(0, b - 6), min(H, b + 7)):
            seg = img[y, xs][~text_mask[y, xs]]
            if len(seg) == 0:
                continue
            c = tuple(int(v) for v in np.median(seg, axis=0))
            d = max(abs(a - q) for a, q in zip(c, body))
            if d > best:
                best, border = d, c
    head_item = rows[0][0]
    body_item = rows[1][0]
    hs = text_style(img, head_item[1:], head_item[0], dpi)
    bs = text_style(img, body_item[1:], body_item[0], dpi)
    sizes = [text_style(img, r[0][1:], r[0][0], dpi).size for r in rows[1:6]]
    return TableStyle(_hex(header), _hex(body), hs.color, bs.color,
                      _hex(border) if border is not None and best >= 8 else None,
                      hs.bold or (hs.size >= bs.size and _weight(img, head_item) > _weight(img, body_item) * 1.15),
                      float(median(sizes)))


def _weight(img, item) -> float:
    """Ink per area of a text box: relative boldness between header and body."""
    _, x, y, w, h = item
    c = img[y:y + h, x:x + w].astype(np.int16)
    if c.size == 0:
        return 0.0
    bg = np.median(np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]]), axis=0)
    return float((np.abs(c - bg).max(axis=2) > 60).mean())
