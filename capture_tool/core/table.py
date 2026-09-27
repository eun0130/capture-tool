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


def _line_positions(profile: np.ndarray, min_len: int) -> list[int]:
    """Indices where a long line runs (merging neighbours that belong to one thick line)."""
    idx = [i for i, v in enumerate(profile) if v >= min_len]
    out: list[int] = []
    for i in idx:
        if out and i - out[-1] <= 2:
            continue
        out.append(i)
    return out


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
    if len(xs) < 3 or len(ys) < 3:   # at least 2 columns and 2 rows of cells
        return None
    return xs, ys


def grid_from_cells(items: list[Item], xs: list[int], ys: list[int]) -> list[list[str]]:
    """Put each OCR box into the cell containing its center; words in one cell are joined."""
    rows, cols = len(ys) - 1, len(xs) - 1
    cells: list[list[list[tuple[float, float, str]]]] = [[[] for _ in range(cols)] for _ in range(rows)]
    for text, x, y, w, h in items:
        cx, cy = x + w / 2, y + h / 2
        c = next((i for i in range(cols) if xs[i] <= cx < xs[i + 1]), None)
        r = next((j for j in range(rows) if ys[j] <= cy < ys[j + 1]), None)
        if c is not None and r is not None:
            cells[r][c].append((y, x, text))
    return [[" ".join(t for _, _, t in sorted(cell)) for cell in row] for row in cells]


def to_tsv(grid: list[list[str]]) -> str:
    return "\n".join("\t".join(re.sub(r"[\t\r\n]+", " ", c) for c in row) for row in grid)
