"""Tables drawn with line characters (terminal / console output such as

    ┌────┬──────┐
    │ D1 │ 내용 │
    ├────┼──────┤

Rows lie between the horizontal rules; the columns are where the rules carry junction marks
(┬ ┼ ┴), which stay put even where the terminal wrapped a long cell and pushed the │ bars of
that line sideways. Each line of each cell is read on its own (the bars never reach the text);
a line that the terminal wrapped to the left edge belongs to the cell it overflowed from."""
from __future__ import annotations

import re

import cv2
import numpy as np

from .table_capture import CapturedTable, TableStyle

INK = 40                 # grey-level difference from the background that counts as ink
RULE_SHARE = 0.5         # a horizontal rule covers at least this share of the width
MIN_RULES = 3            # header + one row at least
GLYPH_GAP = 4            # px; pieces of one letter / one Latin word are closer than this
LATIN_BREAK = 7          # px; a wider gap after a Latin word is a space
BARS = "│|┃ㅣ"


def _hex(bgr) -> str:
    return "#{:02X}{:02X}{:02X}".format(int(bgr[2]), int(bgr[1]), int(bgr[0]))


def _clusters(flags) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(list(flags) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    return out


def _rules(ink: np.ndarray) -> list[int]:
    rows = ink.mean(axis=1) >= RULE_SHARE
    return [int((a + b - 1) / 2) for a, b in _clusters(rows)]


def _columns(ink: np.ndarray, rules: list[int]) -> list[int]:
    """x of the junction marks just under the rules (all but the last), kept when most rules agree."""
    H = ink.shape[0]
    votes = np.zeros(ink.shape[1], int)
    for y in rules[:-1]:
        y0, y1 = y + 3, min(H, y + 7)
        if y1 > y0:
            votes += ink[y0:y1].any(axis=0)
    need = max(2, (len(rules) - 1 + 1) // 2)
    return [int((a + b - 1) / 2) for a, b in _clusters(votes >= need)]


BAR_RUN = 32             # px at 96 dpi; a vertical stroke this tall is a bar (a letter + a junction stub is less)
HANGUL_BREAK = 1.25      # syllable pitch this many times the usual pitch = a space between words


def _bar_pixels(ink: np.ndarray, min_run: int) -> np.ndarray:
    """Pixels of vertical strokes at least min_run tall (the │ bars, shifted or not); letters
    touching a bar keep their own pixels."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, min_run)))
    bars = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, k)
    return cv2.dilate(bars, np.ones((1, 3), np.uint8)) > 0


def _visual_lines(words: list) -> list[list]:
    lines: list[list] = []
    for w in sorted(words, key=lambda w: (w[1][1] + w[1][3]) / 2):
        cy = (w[1][1] + w[1][3]) / 2
        h = w[1][3] - w[1][1]
        if lines and abs(cy - lines[-1][0]) <= 0.5 * max(h, lines[-1][1]):
            lines[-1][2].append(w)
        else:
            lines.append([cy, h, [w]])
    return [sorted(l[2], key=lambda w: w[1][0]) for l in lines]


def _is_hangul(t: str) -> bool:
    return bool(t) and all("\uac00" <= ch <= "\ud7a3" for ch in t)


def _pitch(pt: str, pb, t: str, b) -> float:
    """Distance from the previous syllable to the next one, start to start (or end to end when
    only the next word is a single syllable): the letters' own widths don't disturb it."""
    if len(pt.strip()) == 1:
        return b[0] - pb[0]
    if len(t.strip()) == 1:
        return b[2] - pb[2]
    return (b[0] - pb[2]) * 2.0                     # rare: two long words; gap doubled ~ a pitch


def _join(words: list, step: float) -> str:
    """Words of one cell, left to right. Between Korean syllables a space only where the gap is
    clearly wider than between the letters of a word (step: the usual gap)."""
    out = ""
    for k, (t, b) in enumerate(words):
        t = t.strip()
        if not t or all(ch in BARS for ch in t):
            continue
        if not out:
            out = t
            continue
        pt, pb = words[k - 1]
        if _is_hangul(pt.strip()[-1:]) and _is_hangul(t[:1]):
            space = _pitch(pt, pb, t, b) > HANGUL_BREAK * step
        else:
            space = (b[0] - pb[2]) > LATIN_BREAK
        out += (" " if space else "") + t
    return _strip_bars(out)


def _strip_bars(text: str) -> str:
    text = re.sub(rf"(^|\s)[{BARS}](?=\s|$)", " ", text or "")
    text = text.strip().strip(BARS).strip()
    return " ".join(text.split())


def find_box_table(img, read_words, dpi: float = 96) -> CapturedTable | None:
    """read_words(bgr crop) -> [(text, (x0, y0, x1, y1))] with Korean read syllable by syllable."""
    if img is None or getattr(img, "size", 0) == 0 or min(img.shape[:2]) < 30:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img = np.ascontiguousarray(img[:, :, :3])
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(int)
    bgv = int(np.median(gray))
    ink = np.abs(gray - bgv) > INK
    rules = _rules(ink)
    if len(rules) < MIN_RULES:
        return None
    cols = _columns(ink, rules)
    if len(cols) < 3 or len(cols) > 16:
        return None
    same = gray == bgv
    bg = tuple(int(v) for v in np.median(img[same], axis=0))
    ncol = len(cols) - 1
    clean = img.copy()
    clean[_bar_pixels(ink, int(round(BAR_RUN * dpi / 96)))] = bg      # the │ bars never reach the reader
    for y in rules:
        clean[max(0, y - 3):y + 4] = bg                                  # nor the ─ rules
    words = read_words(clean)                                           # one pass over the whole table
    bands = []
    steps = []
    for top, bot in zip(rules, rules[1:]):
        y0, y1 = top + 3, bot - 2
        if y1 - y0 < 8:
            continue
        mine = [w for w in words if y0 <= (w[1][1] + w[1][3]) / 2 < y1]
        lines = _visual_lines(mine)
        for ln in lines:
            for (t, b), (t2, b2) in zip(ln, ln[1:]):
                if _is_hangul(t.strip()[-1:]) and _is_hangul(t2.strip()[:1]):
                    steps.append(_pitch(t, b, t2, b2))
        bands.append((y0, y1, lines))
    if not bands:
        return None
    step = float(np.percentile(steps, 25)) if steps else 1e9
    bar_px = _bar_pixels(ink, int(round(BAR_RUN * dpi / 96)))
    rows: list[list[str]] = []
    heights = []
    for y0, y1, lines in bands:
        cells: list[list] = [[] for _ in range(ncol)]
        last = None
        for ln in lines:
            ly0 = int(min(b[1] for _, b in ln))
            ly1 = int(max(b[3] for _, b in ln))
            heights.append(ly1 - ly0)
            left = bar_px[max(0, ly0 - 2):ly1 + 2, max(0, cols[0] - 2):cols[0] + 3].any(axis=1).mean() >= 0.6
            if not left and last is not None:              # wrapped by the terminal: back to its cell
                cells[last].append(("\n", None))
                cells[last].extend(ln)
                continue
            got = None
            for c in range(ncol):
                lo = cols[c] if c else -1e9                   # text running past the outer bars
                hi = cols[c + 1] if c < ncol - 1 else 1e9     # still belongs to the outer cells
                mine = [w for w in ln if lo <= (w[1][0] + w[1][2]) / 2 < hi]
                if mine:
                    if cells[c]:
                        cells[c].append(("\n", None))
                    cells[c].extend(mine)
                    got = c
            last = got if got is not None else last
        row = []
        for ws in cells:
            parts, cur = [], []
            for w in ws + [("\n", None)]:
                if w[0] == "\n":
                    if cur:
                        parts.append(_join(cur, step))
                    cur = []
                else:
                    cur.append(w)
            row.append(" ".join(p for p in parts if p))
        rows.append(row)
    if len(rows) < 2 or sum(1 for r in rows for c in r if c) < len(rows):
        return None
    fg_mask = ink.copy()
    for y in rules:
        fg_mask[max(0, y - 2):y + 3] = False
    fg_mask[_bar_pixels(ink, int(round(BAR_RUN * dpi / 96)))] = False
    text_c = np.median(img[fg_mask], axis=0) if fg_mask.any() else (0, 0, 0)
    rule_px = img[rules].reshape(-1, 3)
    on = np.abs(rule_px.mean(axis=1) - bgv) > INK
    rule_c = np.median(rule_px[on], axis=0) if on.any() else text_c
    size = max(8.0, min(20.0, round(float(np.median(heights)) * 0.72 * 72 / dpi * 2) / 2)) if heights else 11.0   # word boxes ~1.4x the font
    style = TableStyle(_hex(bg), _hex(bg), _hex(text_c), _hex(text_c), _hex(rule_c), True, size)
    widths = [(b - a) * 72 / dpi for a, b in zip(cols, cols[1:])]
    return CapturedTable(rows, (cols[0], rules[0], cols[-1] - cols[0], rules[-1] - rules[0]), [], style, widths)
