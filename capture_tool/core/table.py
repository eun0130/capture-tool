"""OCR word boxes -> table grid -> TSV (pastes into Excel cell by cell)."""
from __future__ import annotations

import re
from statistics import median

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


def to_grid(items: list[Item]) -> list[list[str]]:
    if not items:
        return []
    h = median(i[4] for i in items)
    rows = [_cells(r, gap=h) for r in _rows(items, tol=h * 0.5)]
    # column anchors: cluster cell centers across all rows
    centers = sorted(c for row in rows for _, c in row)
    anchors: list[list[float]] = []
    for c in centers:
        if anchors and c - median(anchors[-1]) <= h * 1.5:
            anchors[-1].append(c)
        else:
            anchors.append([c])
    cols = [median(a) for a in anchors]
    grid = []
    for row in rows:
        out = [""] * len(cols)
        for text, c in row:
            k = min(range(len(cols)), key=lambda i: abs(cols[i] - c))
            out[k] = f"{out[k]} {text}".strip()
        grid.append(out)
    return grid


def to_tsv(grid: list[list[str]]) -> str:
    return "\n".join("\t".join(re.sub(r"[\t\r\n]+", " ", c) for c in row) for row in grid)
