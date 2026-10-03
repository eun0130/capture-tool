"""OCR word boxes -> table grid -> TSV (pastes into Excel cell by cell)."""
from __future__ import annotations

import re
from statistics import median

import cv2
import numpy as np

Item = tuple  # (text, x, y, w, h)


def _rows(items: list[Item], tol: float) -> list[list[Item]]:
    rows: list[list[Item]] = []
    for it in sorted(items, key=lambda i: i[2] + i[4] / 2):
        cy = it[2] + it[4] / 2
        if rows:
            row_cy = median(r[2] + r[4] / 2 for r in rows[-1])
            if abs(cy - row_cy) <= tol:
                rows[-1].append(it)
                continue
        rows.append([it])
    return [sorted(r, key=lambda i: i[1]) for r in rows]


def _cells(row: list[Item], gap: float) -> list[tuple[str, float]]:
    """Merge words that sit close together into one cell -> (text, x-center)."""
    cells: list[list[Item]] = []
    for it in row:
        if cells and it[1] - (cells[-1][-1][1] + cells[-1][-1][3]) < gap:
            cells[-1].append(it)
        else:
            cells.append([it])
    out = []
    for c in cells:
        x1 = c[0][1]
        x2 = c[-1][1] + c[-1][3]
        out.append((" ".join(i[0] for i in c), (x1 + x2) / 2))
    return out


def _bands(rows: list[list[Item]]) -> list[list[float]]:
    """Columns of a sheet without ruling lines: x ranges that some cell covers, separated by
    gaps no cell crosses. Rows with a single item (titles) don't take part."""
    use = [r for r in rows if len(r) >= 2] or rows
    bands: list[list[float]] = []
    for x1, x2 in sorted((i[1], i[1] + i[3]) for r in use for i in r):
        if bands and x1 <= bands[-1][1] + 1:
            bands[-1][1] = max(bands[-1][1], x2)
        else:
            bands.append([x1, x2])
    return bands


def _band_of(item: Item, bands: list[list[float]]) -> int:
    x = item[1]
    for k, (a, b) in enumerate(bands):
        if a - 2 <= x <= b:
            return k
    cx = item[1] + item[3] / 2
    return min(range(len(bands)), key=lambda k: abs((bands[k][0] + bands[k][1]) / 2 - cx))


def to_grid(items: list[Item]) -> list[list[str]]:
    if not items:
        return []
    h = median(i[4] for i in items)
    rows = _rows(items, tol=h * 0.5)
    bands = _bands(rows)
    cells = [[[] for _ in bands] for _ in rows]
    for r, row in enumerate(rows):
        for it in row:
            cells[r][_band_of(it, bands)].append(it)
    # a column used by one row only, right next to that row's previous cell, is the rest of
    # that cell ("2026-10-03 입고", "New York"), not a column of its own
    k = len(bands) - 1
    while k > 0:
        used = [r for r in range(len(rows)) if cells[r][k]]
        if len(used) == 1 and cells[used[0]][k - 1]:
            r = used[0]
            left = max(cells[r][k - 1], key=lambda i: i[1] + i[3])
            if min(i[1] for i in cells[r][k]) - (left[1] + left[3]) < h:
                cells[r][k - 1].extend(cells[r][k])
                for row in cells:
                    del row[k]
        k -= 1
    grid = [[" ".join(i[0] for i in sorted(c, key=lambda i: i[1])) for c in row] for row in cells]
    return drop_sheet_headers(grid)


def _col_number(s: str) -> int | None:
    if not re.fullmatch(r"[A-Z]{1,3}", s):
        return None
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def _arith(vals: list[int | None], min_count: int = 2) -> bool:
    """Values counting up by one (an unread cell may be missing)."""
    seen = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(seen) < min_count or len(seen) < 0.6 * len(vals):
        return False
    i0, v0 = seen[0]
    return all(v == v0 + (i - i0) for i, v in seen)


def _trim_empty_edges(grid: list[list[str]]) -> list[list[str]]:
    while grid and not any(c.strip() for c in grid[0]):
        grid = grid[1:]
    while grid and not any(c.strip() for c in grid[-1]):
        grid = grid[:-1]
    while grid and grid[0] and not any(row[0].strip() for row in grid):
        grid = [row[1:] for row in grid]
    while grid and grid[0] and not any(row[-1].strip() for row in grid):
        grid = [row[:-1] for row in grid]
    return grid


def _int(s: str) -> int | None:
    s = s.strip()
    return int(s) if s.isdigit() else None


def drop_sheet_headers(grid: list[list[str]]) -> list[list[str]]:
    """Excel's own column letters (A B C) and row numbers (1 2 3) captured with the cells are
    removed. Letters count only together with row numbers (A/B data stays); a number strip
    alone counts only when it runs through every row including the first, where a real
    numbered column has its title ("No", "번호")."""
    grid = _trim_empty_edges(grid)
    if len(grid) < 2 or len(grid[0]) < 2:
        return grid
    letters = [_col_number(c.strip()) for c in grid[0][1:]]
    numbers = [_int(row[0]) for row in grid[1:]]
    if grid[0][0].strip() == "" and _arith(letters) and _arith(numbers):
        return [row[1:] for row in grid[1:]]
    first = [_int(row[0]) for row in grid]
    if len(grid) >= 3 and all(v is not None for v in first) and _arith(first):
        return [row[1:] for row in grid]
    return grid


# Guards against ordinary screens being read as a spreadsheet (v0.3.3 took a dark UI screen
# for a 233x316 "table" and PowerPoint froze on the ~70k cells).
MAX_LINE_THICK = 4    # px; a thicker dark band is a filled area (title bar, dark mode), not a rule
MIN_CELL = 8          # px; rules packed tighter than this are a hatch/texture, not cells
MAX_ROWS = 500
MAX_COLS = 60
MIN_FILL = 0.25       # share of cells that must hold text


MAX_BAND = 120        # px; a filled run up to this tall is a coloured row (header fill)


def _line_positions(profile: np.ndarray, min_len: int) -> list[int]:
    """Centers of thin runs where a long line runs. A filled band (coloured header row) hides
    the lines at its edges, so its two edges count too - but only next to real thin lines;
    other thick runs (title bars, dark panels) are skipped."""
    out: list[int] = []
    edges: list[int] = []
    start = None
    for i, v in enumerate(list(profile) + [0]):
        if v >= min_len:
            if start is None:
                start = i
        elif start is not None:
            if i - start <= MAX_LINE_THICK:
                out.append(start + (i - 1 - start) // 2)
            elif MIN_CELL <= i - start <= MAX_BAND:
                edges += [start, i - 1]
            start = None
    if len(out) >= 2 and edges:
        for e in edges:
            if all(abs(e - p) > MAX_LINE_THICK for p in out):
                out.append(e)
        out.sort()
    return out


def _regular(pos: list[int], limit: int) -> bool:
    return 3 <= len(pos) <= limit + 1 and all(b - a >= MIN_CELL for a, b in zip(pos, pos[1:]))


def detect_grid(img: np.ndarray) -> tuple[list[int], list[int]] | None:
    """Spreadsheet-style ruling lines -> (column x positions, row y positions), or None.

    Excel/Sheets grid lines are thin, light-gray and run across the whole table, so we keep
    long horizontal/vertical runs of non-white pixels and read their positions."""
    if img is None or img.size == 0 or min(img.shape[:2]) < 10:
        return None
    gray = img if img.ndim == 2 else cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    dark = (gray < 235).astype(np.uint8)
    h, w = dark.shape
    horiz = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((1, max(20, w // 4)), np.uint8))
    vert = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((max(12, h // 4), 1), np.uint8))
    ys = _line_positions(horiz.sum(axis=1), max(20, int(w * 0.25)))
    xs = _line_positions(vert.sum(axis=0), max(12, int(h * 0.25)))
    # at least 2 columns and 2 rows of cells, evenly readable, not absurdly many
    if not (_regular(xs, MAX_COLS) and _regular(ys, MAX_ROWS)):
        return None
    return xs, ys


def table_is_plausible(grid: list[list[str]]) -> bool:
    """Enough cells hold text for this to be a table someone wants in Excel."""
    if not grid or not grid[0] or len(grid) > MAX_ROWS or len(grid[0]) > MAX_COLS:
        return False
    total = len(grid) * len(grid[0])
    filled = sum(1 for row in grid for c in row if c)
    return filled >= 3 and filled / total >= MIN_FILL


def grid_from_cells(items: list[Item], xs: list[int], ys: list[int]) -> list[list[str]]:
    """Put each OCR box into the cell containing its center; words in one cell are joined."""
    rows, cols = len(ys) - 1, len(xs) - 1
    if rows < 1 or cols < 1:
        return []
    cells: list[list[list[tuple[float, float, str]]]] = [[[] for _ in range(cols)] for _ in range(rows)]
    for text, x, y, w, h in items:
        cx, cy = x + w / 2, y + h / 2
        c = next((i for i in range(cols) if xs[i] <= cx < xs[i + 1]), None)
        r = next((j for j in range(rows) if ys[j] <= cy < ys[j + 1]), None)
        if c is not None and r is not None:
            cells[r][c].append((y, x, text))
    grid = [[_cell_text(cell) for cell in row] for row in cells]
    # slivers between a filled band's edge and a nearby line hold no text: drop them
    hs = [b - a for a, b in zip(ys, ys[1:])]
    ws = [b - a for a, b in zip(xs, xs[1:])]
    mh, mw = median(hs), median(ws)
    keep_r = [r for r in range(rows) if hs[r] >= 0.6 * mh or any(grid[r])]
    keep_c = [c for c in range(cols) if ws[c] >= 0.6 * mw or any(grid[r][c] for r in range(rows))]
    grid = [[grid[r][c] for c in keep_c] for r in keep_r]
    return drop_sheet_headers(grid)


def _cell_text(cell: list[tuple[float, float, str]]) -> str:
    """Words of one cell in reading order (lines by y, then x), minus cell borders read as '|'."""
    if not cell:
        return ""
    cell = sorted(cell)
    lines: list[list[tuple[float, float, str]]] = []
    for y, x, t in cell:
        if lines and y - lines[-1][0][0] <= 8:
            lines[-1].append((y, x, t))
        else:
            lines.append([(y, x, t)])
    words = []
    for ln in lines:
        for _, _, t in sorted(ln, key=lambda w: w[1]):
            for tok in t.split():
                tok = tok.strip("|") if tok.startswith("|") or tok.endswith("|") else tok
                if tok:
                    words.append(tok)
    return " ".join(words)


def to_tsv(grid: list[list[str]]) -> str:
    return "\n".join("\t".join(re.sub(r"[\t\r\n]+", " ", c) for c in row) for row in grid)
