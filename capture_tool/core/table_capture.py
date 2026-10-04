"""A table inside a capture (light or dark page, with or without ruling lines) -> rows of
cells plus its look (header/body fill, text colours, border, font size, column widths), so it
can go to PowerPoint as a real table instead of loose text boxes."""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

import numpy as np

from .shapes import _dist, _hex, _to_bgr, text_style
from .table import _band_of, _bands, _rows, detect_grid, grid_from_cells, to_grid

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
    cut_edge: bool = False                      # letters cut by the capture's edge: some may be misread
    runs: dict = field(default_factory=dict)    # (row, col) -> [(text, "#RRGGBB" | None)]: words in another colour


def plain_style(font_size: float = 11) -> TableStyle:
    """White cells, black text, thin black lines, bold header: a table for documents."""
    return TableStyle("#FFFFFF", "#FFFFFF", "#000000", "#000000", "#000000", True, float(font_size))


def _median_color(img, mask):
    px = img[mask]
    return None if len(px) == 0 else tuple(int(v) for v in np.median(px, axis=0))


def _real_text(t: str) -> bool:
    """OCR bits of borders and corners ('−−−−', '¶', '‖', '|') hold no letter or digit."""
    return any(ch.isalnum() for ch in t)


def _table_ok(rows, min_rows: int):
    """Grid of a run of OCR rows if it reads as a table, else None."""
    if len(rows) < min_rows or len(rows) > MAX_ROWS:
        return None
    if sum(len(r) >= 2 for r in rows) < MIN_MULTI * len(rows):
        return None
    centers = [median(i[2] + i[4] / 2 for i in r) for r in rows]
    gaps = [b - a for a, b in zip(centers, centers[1:])]
    if gaps and np.std(gaps) > MAX_SPACING_CV * np.mean(gaps):
        return None
    grid = to_grid([i for r in rows for i in r])
    if not grid or len(grid) < min_rows or not (MIN_COLS <= len(grid[0]) <= MAX_COLS):
        return None
    if sum(1 for r in grid for c in r if c) < MIN_FILL * len(grid) * len(grid[0]):
        return None
    return grid


def _best_block(rows):
    """The run of consecutive rows that makes the biggest table: other text captured above,
    beside or below it (another window, a heading) stays out."""
    n = len(rows)
    spans = [(0, n)] if n > 120 else [(a, b) for a in range(n) for b in range(a + MIN_ROWS, n + 1)]
    best = None
    for a, b in spans:
        if len(rows[a]) < 2 or len(rows[b - 1]) < 2:
            continue                                   # a one-line title/note sits outside the table
        grid = _table_ok(rows[a:b], MIN_ROWS)
        if grid is None:
            continue
        score = (len(grid) * len(grid[0]), -(b - a))
        if best is None or score > best[0]:
            best = (score, a, b, grid)
    return None if best is None else best[1:]


WRAP_TIGHT = 0.6        # a line ending this close (in letters) to its column's edge was cut mid-word
WORD_END = set("고를을는은에의와과며면도")   # Korean particles / endings: the word is complete there


def join_wrapped(parts, limit: float, char_w: float) -> str:
    """Lines of one cell (text, right edge) back into one text. A line that runs to the column's
    edge was cut by the wrapping, maybe in the middle of a word ("클라이언트" | "처럼"): joined
    without a space. A line that stops earlier ended at a space."""
    out = ""
    prev_right = None
    for text, right in parts:
        text = text.strip()
        if not text:
            continue
        if not out:
            out = text
        else:
            cut = limit - prev_right < WRAP_TIGHT * char_w
            glue = cut and out[-1].isalnum() and text[0].isalnum() and out[-1] not in WORD_END
            out += ("" if glue else " ") + text
        prev_right = right
    return out


def _separators(img, y1: int, y2: int, x1: int, x2: int) -> list[int]:
    """y of the lines drawn across the table between its rows (also lines broken at the column
    gaps), found against the table's own background."""
    H, W = img.shape[:2]
    y1, y2, x1, x2 = max(0, y1), min(H, y2), max(0, x1), min(W, x2)
    if y2 - y1 < 4 or x2 - x1 < 20:
        return []
    area = img[y1:y2, x1:x2].astype(np.int16)
    bg = np.median(area.reshape(-1, 3), axis=0)
    diff = np.abs(area - bg).max(axis=2) > 20
    rows = diff.mean(axis=1) >= 0.6
    out, start = [], None
    for i, v in enumerate(list(rows) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start <= 6:                             # a line, not a filled band
                out.append(y1 + (start + i - 1) // 2)
            start = None
    return out


def _merge_by_separators(img, rows, grid, x1, x2, h):
    """Rows between two separator lines are one table row: their lines are rejoined per cell."""
    centers = [median(i[2] + i[4] / 2 for i in r) for r in rows]
    top = int(min(i[2] for r in rows for i in r) - h)
    bottom = int(max(i[2] + i[4] for r in rows for i in r) + h)
    seps = [y for y in _separators(img, top, bottom, x1, x2) if centers[0] < y < centers[-1]]
    if not seps:
        return rows, grid
    band = [sum(1 for y in seps if y < c) for c in centers]
    if len(set(band)) == len(rows) or len(set(band)) < 2:
        return rows, grid
    bands = _bands(rows)
    if len(bands) != len(grid[0]):
        return rows, grid
    limits = [b[1] for b in bands]
    new_rows, new_grid = [], []
    for k in sorted(set(band)):
        members = [r for r, bk in zip(rows, band) if bk == k]
        cells = []
        for c in range(len(bands)):
            parts = []
            for r in members:
                its = sorted((i for i in r if _band_of(i, bands) == c), key=lambda i: i[1])
                if its:
                    parts.append((" ".join(i[0] for i in its), max(i[1] + i[3] for i in its)))
            cells.append(join_wrapped(parts, limits[c], h))
        new_rows.append([i for r in members for i in r])
        new_grid.append(cells)
    return new_rows, new_grid


def _caption(rows, a, b, gap):
    """Single-line rows right above / below the table (its title or note)."""
    out = []
    cy = lambda r: median(i[2] + i[4] / 2 for i in r)     # noqa: E731
    if a > 0 and len(rows[a - 1]) == 1 and cy(rows[a]) - cy(rows[a - 1]) <= 2.0 * gap:
        out.append(rows[a - 1][0])
    if b < len(rows) and len(rows[b]) == 1 and cy(rows[b]) - cy(rows[b - 1]) <= 2.0 * gap:
        out.append(rows[b][0])
    return [(i[0], tuple(i[1:])) for i in out]


def find_table(img, lines, shapes, dpi: float = 96) -> CapturedTable | None:
    """lines: (text, (x, y, w, h), score); shapes: Detected from the shape search."""
    if img is None or img.size == 0:
        return None
    img = _to_bgr(img)
    H, W = img.shape[:2]
    for s in shapes or []:
        if s.kind not in ("line", "arrow", "text") and s.w * s.h >= DIAGRAM_SHARE * W * H:
            return None
    items = [(t.strip(), *b) for t, b, _ in lines if t and t.strip() and _real_text(t)]
    if len(items) < 2 * MIN_COLS:
        return None
    h = median(i[4] for i in items)

    found = detect_grid(img)                        # ruling lines (light or dark page): exact cells
    if found is not None:
        xs, ys = found
        inside = [i for i in items if xs[0] <= i[1] + i[3] / 2 <= xs[-1] and ys[0] <= i[2] + i[4] / 2 <= ys[-1]]
        grid = grid_from_cells(inside, xs, ys) if inside else []
        if (grid and len(grid) >= 2 and MIN_COLS <= len(grid[0]) <= MAX_COLS
                and sum(1 for r in grid for c in r if c) >= 0.5 * len(grid) * len(grid[0])):
            rows = _rows(inside, tol=h * 0.5)
            centers = [(a + b) / 2 for a, b in zip(ys, ys[1:])]
            gap = float(np.mean(np.diff(ys)))
            above = [i for i in items if i not in inside and ys[0] - 2.0 * gap <= i[2] + i[4] / 2 < ys[0]]
            outside = [(i[0], tuple(i[1:])) for i in above if len(above) == 1]
            style = _style(img, rows, centers, gap, inside, xs[0], xs[-1], ys[0], ys[-1], dpi)
            widths = [(b - a) * 72 / dpi for a, b in zip(xs, xs[1:])]
            if len(widths) != len(grid[0]):
                widths = [(xs[-1] - xs[0]) * 72 / dpi / len(grid[0])] * len(grid[0])
            return CapturedTable(grid, (xs[0], ys[0], xs[-1] - xs[0], ys[-1] - ys[0]), outside, style, widths)

    all_rows = _rows(items, tol=h * 0.5)
    block = _best_block(all_rows)
    if block is None:
        return None
    a, b, grid = block
    rows = all_rows[a:b]
    x_lo = min(i[1] for r in rows for i in r)
    x_hi = max(i[1] + i[3] for r in rows for i in r)
    rows, grid = _merge_by_separators(img, rows, grid, int(x_lo - h), int(x_hi + h), h)
    centers = [median(i[2] + i[4] / 2 for i in r) for r in rows]
    gap = float(np.mean(np.diff(centers)))
    outside = _caption(all_rows, a, b, gap)
    table_items = [i for r in rows for i in r]
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
    starts = [band[0] for band in _bands(rows)]
    if len(starts) == len(grid[0]):
        lefts = [bx1] + [st - pad for st in starts[1:]]
        widths = [max(1.0, r - l) for l, r in zip(lefts, lefts[1:] + [bx2])]
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
