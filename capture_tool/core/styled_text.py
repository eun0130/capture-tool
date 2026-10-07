"""Text of a capture with its look: colour, bold and background of every stretch of letters, the
page colour, indentation, monospace or not - read from the pixels around the letters the reader
found. Goes on the clipboard as HTML (Excel, PowerPoint, Word, web editors) next to plain text."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher

import cv2
import numpy as np

from .clipboard_payload import HTML, UNICODE, cf_html

INK = 36                 # a pixel this far from the paper behind it is ink
SAME_COLOR = 44          # letters whose colours are this close are one colour
SAME_BG = 26             # a background this far from the page colour is a highlight / a block
BOLD_RATIO = 1.3         # strokes this much thicker than the text's usual stroke are bold
MONO_FIT = 0.3           # monospace: word widths fit letters x one width this closely (in letters)
MAX_LINES = 3000
MAX_INDENT = 60
MONO_FONT = "Consolas,D2Coding,Malgun Gothic,monospace"      # (no quotes: they sit inside a quoted attribute)
SANS_FONT = "Malgun Gothic,sans-serif"


@dataclass
class Run:
    text: str
    color: str | None = None          # "#RRGGBB"
    bg: str | None = None             # highlight behind these letters (None: the page colour)
    bold: bool = False


@dataclass
class StyledText:
    lines: list[list[Run]] = field(default_factory=list)
    bg: str = "#FFFFFF"               # page colour
    fg: str = "#000000"               # the colour most letters have
    mono: bool = False
    size: float = 11.0                # points


# --- small helpers -----------------------------------------------------------------------------------

def _hex(bgr) -> str:
    return "#%02X%02X%02X" % (int(bgr[2]), int(bgr[1]), int(bgr[0]))


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _far(a, b) -> int:
    return max(abs(int(x) - int(y)) for x, y in zip(a, b))


def _mode_color(px: np.ndarray):
    """The colour most pixels have (a flat page or fill), else their median."""
    px = px.reshape(-1, 3)
    if len(px) == 0:
        return None
    if len(px) > 40000:
        px = px[:: len(px) // 40000 + 1]
    q = (px.astype(np.int32) >> 2)
    keys = (q[:, 0] << 12) | (q[:, 1] << 6) | q[:, 2]
    u, inv, n = np.unique(keys, return_inverse=True, return_counts=True)
    top = int(n.argmax())
    if n[top] >= 0.25 * len(px):
        return tuple(int(v) for v in np.median(px[inv.reshape(-1) == top], axis=0))
    return tuple(int(v) for v in np.median(px, axis=0))


def _weight(ch: str) -> float:
    if ch == " ":
        return 0.5
    if "ᄀ" <= ch <= "ᇿ" or "぀" <= ch <= "鿿" or "가" <= ch <= "힣" or "＀" <= ch <= "￯":
        return 1.0
    if ch.isascii() and ch.isalnum():
        return 0.6
    return 0.4


def _wide(ch: str) -> bool:
    return _weight(ch) == 1.0


def _cells(text: str) -> float:
    """Width of text in monospace cells (Korean letters take two)."""
    return sum(2 if _wide(c) else 1 for c in text)


def tidy(runs: list[Run]) -> list[Run]:
    """Empty runs go, blanks join the letters before them, neighbours of one look become one run."""
    out: list[Run] = []
    pending = ""
    for r in runs:
        if not r.text:
            continue
        if not r.text.strip():
            if out:
                out[-1] = replace(out[-1], text=out[-1].text + r.text)
            else:
                pending += r.text
            continue
        r = replace(r, text=pending + r.text)
        pending = ""
        if out and out[-1].bold == r.bold and out[-1].bg == r.bg and (
                out[-1].color == r.color or (out[-1].color and r.color and _far(_rgb(out[-1].color), _rgb(r.color)) <= 12)):
            out[-1] = replace(out[-1], text=out[-1].text + r.text)
        else:
            out.append(r)
    if pending and not out:
        return []
    return out


# --- reading the look off the pixels -------------------------------------------------------------------

def _to_bgr(img):
    if img is None or getattr(img, "size", 0) == 0:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return np.ascontiguousarray(img[:, :, :3])


def _look(img: np.ndarray, box, back=None) -> tuple | None:
    """(letter colour, colour behind the letters, stroke measure, ink top, ink bottom) inside a box.
    back: the colour behind the letters when it is known (a single letter's box can't tell)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    if x1 - x0 < 2 or y1 - y0 < 3:
        return None
    c = img[y0:y1, x0:x1]
    known = back is not None
    if not known:
        back = _mode_color(c)
    d = np.abs(c.astype(np.int16) - np.array(back, np.int16)).max(axis=2)
    m = d > INK
    n = int(m.sum())
    if n < 4:
        return None
    if n > 0.5 * m.size and not known:                 # more "ink" than paper: the paper is the other colour
        back = _mode_color(c[m])
        d = np.abs(c.astype(np.int16) - np.array(back, np.int16)).max(axis=2)
        m = d > INK
        n = int(m.sum())
        if n < 4:
            return None
    core = c[d >= np.percentile(d[m], 70)]
    color = tuple(int(v) for v in np.median(core, axis=0))
    rows = np.flatnonzero(m.any(axis=1))
    return color, back, n, y0 + int(rows[0]), y0 + int(rows[-1]) + 1


def _stroke(img: np.ndarray, box, text: str) -> float | None:
    """Stroke thickness of a word as a share of its font size (ink area / outline length, the
    font size from the ink height of these very letters). Thicker than the text's usual: bold."""
    from .shapes import _em_factor
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    c = img[max(0, y0):y1, max(0, x0):x1].astype(np.int16)
    if c.shape[0] < 3 or c.shape[1] < 3:
        return None
    paper = np.median(np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]]), axis=0)
    d = np.abs(c - paper).max(axis=2)
    m = d > max(40, int(d.max() * 0.5))
    if m.sum() < 6:
        return None
    rows = np.flatnonzero(m.any(axis=1))
    em = (rows[-1] - rows[0] + 1) / _em_factor(text)
    mk = m.astype(np.uint8)
    contours, _ = cv2.findContours(mk, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    return 2.0 * float(mk.sum()) / max(sum(cv2.arcLength(k, True) for k in contours), 1.0) / max(em, 1.0)


def _char_boxes(text: str, box, words, mono: bool = False) -> list[tuple | None]:
    """A box (x0, y0, x1, y1) for every character of text. With the reader's word boxes each
    word's letters share its box by their widths (equal cells in a monospace font); without,
    the whole line box is shared."""
    weight = (lambda ch: 2.0 if _wide(ch) else 1.0) if mono else _weight
    x, y, w, h = box
    out: list[tuple | None] = [None] * len(text)
    idx = [i for i, ch in enumerate(text) if ch != " "]
    letters = "".join(text[i] for i in idx)
    placed = False
    if words:
        seq, boxes = [], []
        for wt, wb in words:
            t = str(wt).replace(" ", "")
            if not t:
                continue
            ws = [weight(ch) for ch in t]
            total, acc = sum(ws), 0.0
            for ch, wgt in zip(t, ws):
                a = wb[0] + (wb[2] - wb[0]) * acc / total
                acc += wgt
                b = wb[0] + (wb[2] - wb[0]) * acc / total
                seq.append(ch)
                boxes.append((a, wb[1], b, wb[3]))
        if seq:
            sm = SequenceMatcher(None, letters, "".join(seq), autojunk=False)
            hit = 0
            for blk in sm.get_matching_blocks():
                for k in range(blk.size):
                    out[idx[blk.a + k]] = boxes[blk.b + k]
                    hit += 1
            placed = hit >= 0.6 * max(1, len(letters))
            if placed:                                 # letters the two readings disagree on: between neighbours
                for n_, i in enumerate(idx):
                    if out[i] is None:
                        prev = next((out[idx[k]] for k in range(n_ - 1, -1, -1) if out[idx[k]] is not None), None)
                        nxt = next((out[idx[k]] for k in range(n_ + 1, len(idx)) if out[idx[k]] is not None), None)
                        if prev is not None and nxt is not None and nxt[0] > prev[2]:
                            out[i] = (prev[2], y, nxt[0], y + h)
    if not placed:
        out = [None] * len(text)
        ws = [weight(ch) if ch != " " else (1.0 if mono else 0.5) for ch in text]
        total, acc = sum(ws) or 1.0, 0.0
        for i, wgt in enumerate(ws):
            a = x + w * acc / total
            acc += wgt
            out[i] = (a, y, x + w * acc / total, y + h) if text[i] != " " else None
    return out


def _snap_palette(colors: list[tuple], counts: list[int], tol: int) -> dict:
    """Close colours become one (the same keyword colour read twice differs by a few levels)."""
    order = sorted(range(len(colors)), key=lambda i: -counts[i])
    centres: list[tuple] = []
    mapping = {}
    for i in order:
        c = colors[i]
        hit = next((k for k in centres if _far(k, c) <= tol), None)
        if hit is None:
            centres.append(c)
            hit = c
        mapping[c] = hit
    return mapping


@dataclass
class _Piece:
    text: str
    box: tuple                 # x, y, w, h
    chars: list                # per character: (colour, background, top, bottom) or None
    cboxes: list
    bold: list = field(default_factory=list)


def _rows(pieces: list[_Piece]) -> list[list[_Piece]]:
    rows: list[list[_Piece]] = []
    for p in sorted(pieces, key=lambda p: p.box[1] + p.box[3] / 2):
        cy = p.box[1] + p.box[3] / 2
        if rows:
            last = rows[-1][0]
            if abs(cy - (last.box[1] + last.box[3] / 2)) <= max(last.box[3], p.box[3]) * 0.5:
                rows[-1].append(p)
                continue
        rows.append([p])
    return [sorted(r, key=lambda p: p.box[0]) for r in rows]


def _corner(mask: np.ndarray) -> str | None:
    """A tree corner: an upright stroke at the left with one stroke going right from it."""
    h, w = mask.shape
    if h < 5 or w < 4 or float(mask.mean()) > 0.5:
        return None
    col = mask.mean(axis=0)
    row = mask.mean(axis=1)
    if col[: max(1, w // 3)].max() < 0.8:
        return None
    strong = np.flatnonzero(row >= 0.8)
    if not len(strong):
        return None
    at = float(strong.mean()) / h
    return "└" if at >= 0.72 else ("├" if 0.3 <= at <= 0.7 else None)


def _symbol(mask: np.ndarray, em: float, where: float) -> str | None:
    """A mark the reader has no letter for, by its shape and its height in the row (`where`: its
    centre, 0 top .. 1 bottom): a dot, a filled box, a quote tick, a tree corner."""
    h, w = mask.shape
    if h < 2 or w < 2:
        return None
    fill = float(mask.mean())
    if max(w, h) <= 0.45 * em and h >= w and fill >= 0.55 and where <= 0.38:
        return "'"                                     # a small tick high in the row
    if 0.75 <= w / h <= 1.33 and 0.3 <= where <= 0.75 and min(w, h) >= 3:
        if fill >= 0.9:
            return "■" if min(w, h) >= 0.3 * em else "•"
        if fill >= 0.68:
            return "●" if min(w, h) >= 0.36 * em else "•"
    if h >= 0.45 * em and w >= 0.3 * em:
        return _corner(mask)
    return None


def _find_symbols(img, page, rows, em: float) -> list[_Piece]:
    """Marks standing in a row of text that the reader did not return."""
    d = np.abs(img.astype(np.int16) - np.array(page, np.int16)).max(axis=2)
    ink = (d > INK).astype(np.uint8)
    for row in rows:
        for p in row:
            x, y, w, h = (int(round(v)) for v in p.box)
            ink[max(0, y - 2):y + h + 2, max(0, x - 3):x + w + 3] = 0
    out = []
    for row in rows:
        y0 = int(min(p.box[1] for p in row))
        y1 = int(max(p.box[1] + p.box[3] for p in row))
        top = max(0, y0 - 2)
        band = ink[top:y1 + 2]
        if not band.any():
            continue
        n, _, stats, _ = cv2.connectedComponentsWithStats(band, connectivity=8)
        found = []
        for j in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[j])
            if max(w, h) > 1.5 * em or area < 4:
                continue
            where = (y + h / 2) / max(1, band.shape[0])
            ch = _symbol(band[y:y + h, x:x + w] > 0, em, where)
            if ch is None:
                continue
            look = _look(img, (x - 1, top + y - 1, x + w + 1, top + y + h + 1), page)
            found.append([ch, x, w, (look[0], look[1], top + y, top + y + h) if look else None])
        found.sort(key=lambda f: f[1])
        merged = []
        for f in found:                                # two ticks side by side are one double quote
            if merged and merged[-1][0] == "'" and f[0] == "'" and f[1] - (merged[-1][1] + merged[-1][2]) <= 0.3 * em:
                merged[-1][0] = '"'
                merged[-1][2] = f[1] + f[2] - merged[-1][1]
            else:
                merged.append(f)
        for ch, x, w, style in merged:
            out.append(_Piece(ch, (x, y0, w, y1 - y0), [style], [(x, y0, x + w, y1)], [False]))
    return out


def _is_mono(words) -> tuple[bool, float]:
    """Monospace: an English word's width is its letters times one fixed width (plus the same
    little margin); with letters of different widths that never fits."""
    n, w = [], []
    for wt, wb in words:
        t = str(wt)
        if len(t) >= 2 and t.isascii() and " " not in t:      # punctuation takes a cell too
            n.append(len(t))
            w.append(wb[2] - wb[0])
    if len(n) < 4 or len(set(n)) < 3:
        return False, 0.0
    cell, pad = np.polyfit(np.array(n, float), np.array(w, float), 1)
    if cell <= 2:
        return False, 0.0
    resid = np.array(w) - (cell * np.array(n) + pad)
    return float(np.std(resid)) <= MONO_FIT * cell and abs(pad) <= 1.5 * cell, float(cell)


def _blank_between(ink_cols: np.ndarray, a: float, b: float) -> float | None:
    """Longest run of blank columns around the stretch a..b of a row's ink profile."""
    lo, hi = max(0, int(a) - 2), min(len(ink_cols), int(b) + 3)
    if hi <= lo:
        return None
    best = run = 0
    for v in ink_cols[lo:hi]:
        run = 0 if v else run + 1
        best = max(best, run)
    return float(best)


def read_styled(img, recognize, read_words=None, dpi: float = 96) -> StyledText | None:
    """recognize(img) -> lines with .text and .box (x, y, w, h), optionally .words
    [(text, (x0, y0, x1, y1))]; read_words(img) gives those word boxes when the lines carry none."""
    img = _to_bgr(img)
    if img is None or min(img.shape[:2]) < 8:
        return None
    lines = [l for l in (recognize(img) or []) if (l.text or "").strip()]
    if not lines:
        return None
    words = [w for l in lines for w in (getattr(l, "words", None) or ())]
    if not words and read_words is not None:
        try:
            words = list(read_words(img) or [])
        except Exception:  # noqa: BLE001 - no word boxes: the line boxes still give the look
            words = []
    page = _mode_color(img)
    mono, cell = _is_mono(words)

    pieces: list[_Piece] = []
    for l in lines:
        x, y, w, h = l.box
        mine = [wd for wd in words
                if x - 2 <= (wd[1][0] + wd[1][2]) / 2 <= x + w + 2 and y - 2 <= (wd[1][1] + wd[1][3]) / 2 <= y + h + 2]
        mine.sort(key=lambda wd: wd[1][0])
        text = " ".join(l.text.split("\n")).strip()
        cb = _char_boxes(text, l.box, mine, mono)
        pieces.append(_Piece(text, tuple(l.box), [None] * len(text), cb))

    for row in _rows(pieces):                          # one stretch found twice: the earlier piece gives way
        for a, b in zip(row, row[1:]):
            while a.text and a.cboxes[-1] is not None and (a.cboxes[-1][0] + a.cboxes[-1][2]) / 2 >= b.box[0] + 1:
                a.text, a.cboxes, a.chars = a.text[:-1], a.cboxes[:-1], a.chars[:-1]
            a.text = a.text.rstrip()
            a.cboxes, a.chars = a.cboxes[:len(a.text)], a.chars[:len(a.text)]
    pieces = [p for p in pieces if p.text]

    if mono:                                           # letters sit on a grid: exact boxes, exact blanks
        cell = _pitch(img, pieces, cell)
        pieces = [_on_grid(img, p, cell) for p in pieces]
    stroke_of: list[tuple] = []                        # (piece, start, end, stroke / font size, korean?)
    for p in pieces:
        x, y, w, h = p.box
        p.bold = [False] * len(p.text)
        for m in re.finditer(r"\S+", p.text):
            bx = [p.cboxes[k] for k in range(m.start(), m.end()) if p.cboxes[k] is not None]
            if not bx:
                continue
            word = _look(img, (min(b[0] for b in bx) - 1, y, max(b[2] for b in bx) + 1, y + h))
            if not word:
                continue
            for i in range(m.start(), m.end()):         # each letter against the word's paper
                b = p.cboxes[i]
                if b is None:
                    continue
                inset = 0.15 * (b[2] - b[0]) if b[2] - b[0] >= 6 else 0
                look = _look(img, (b[0] + inset, y, b[2] - inset, y + h), word[1])
                p.chars[i] = (look[0], look[1], look[3], look[4]) if look else None
            v = _stroke(img, (min(b[0] for b in bx) - 1, y, max(b[2] for b in bx) + 1, y + h), m.group()) \
                if len(m.group()) >= 2 else None
            if v:
                korean = sum(_wide(c) for c in m.group()) * 2 > len(m.group())
                stroke_of.append((p, m.start(), m.end(), v, korean))
    for korean in (False, True):                       # strokes clearly thicker than the usual: bold
        kind = [s for s in stroke_of if s[4] == korean]
        if len(kind) < 3:
            continue
        usual = float(np.median([s[3] for s in kind]))
        for p, a, b, v, _ in kind:
            if v > BOLD_RATIO * usual:
                p.bold[a:b] = [True] * (b - a)

    heights = [c[3] - c[2] for p in pieces for c in p.chars if c]
    em = float(np.percentile(heights, 75)) / 0.72 if heights else float(np.median([p.box[3] for p in pieces]))
    rows = _rows(pieces)
    for row in rows:                                   # "L" standing alone above the baseline is a tree corner
        bottoms = [c[3] for p in row for c in p.chars if c]
        base = float(np.median(bottoms)) if len(bottoms) >= 3 else None
        for p in row:
            for m in re.finditer(r"(?<!\S)[LlI|ㄴ](?!\S)", p.text):
                c, b = p.chars[m.start()], p.cboxes[m.start()]
                if c is None or b is None or base is None or base - c[3] < 0.12 * em:
                    continue
                x0, x1 = max(0, int(b[0]) - 2), int(b[2]) + 3       # the whole mark: the reader's box may hold half
                ry0 = max(0, int(min(q.box[1] for q in row)) - 2)
                ry1 = int(max(q.box[1] + q.box[3] for q in row)) + 2
                cut = np.abs(img[ry0:ry1, x0:x1].astype(np.int16) - np.array(c[1], np.int16)).max(axis=2) > INK
                cols_, rows_ = np.flatnonzero(cut.any(axis=0)), np.flatnonzero(cut.any(axis=1))
                sym = _corner(cut[rows_[0]:rows_[-1] + 1, cols_[0]:cols_[-1] + 1]) if len(cols_) else None
                if sym:
                    p.text = p.text[:m.start()] + sym + p.text[m.end():]
    try:
        extra = _find_symbols(img, page, rows, em)
    except cv2.error:
        extra = []
    if extra:
        rows = _rows(pieces + extra)
    space = cell if mono and cell > 0 else max(3.0, 0.3 * em)

    tally: dict[tuple, int] = {}                       # one palette for the whole text
    btally: dict[tuple, int] = {}
    for p in pieces + extra:
        for c in p.chars:
            if c:
                tally[c[0]] = tally.get(c[0], 0) + 1
                btally[c[1]] = btally.get(c[1], 0) + 1
    if not tally:
        fg = (0, 0, 0) if sum(page) > 380 else (255, 255, 255)
        snap, bsnap = {}, {}
    else:
        snap = _snap_palette(list(tally), list(tally.values()), SAME_COLOR)
        bsnap = _snap_palette(list(btally), list(btally.values()), SAME_BG)
        weight: dict[tuple, int] = {}
        for c, n in tally.items():
            weight[snap[c]] = weight.get(snap[c], 0) + n
        fg = max(weight, key=weight.get)

    left = min(r[0].box[0] for r in rows)
    centres = [float(np.median([p.box[1] + p.box[3] / 2 for p in r])) for r in rows]
    steps = [b - a for a, b in zip(centres, centres[1:])]
    pitch = float(np.median([s for s in steps if s <= 1.5 * min(steps)])) if steps else 0.0

    out: list[list[Run]] = []
    for k, row in enumerate(rows):
        if k and pitch > 0:
            out += [[] for _ in range(max(0, min(3, int(round(steps[k - 1] / pitch)) - 1)))]
        runs: list[Run] = []
        width = 0                                      # cells written so far (monospace)
        prev_end = None
        for p in row:
            if mono:                                   # every piece starts in its own column
                target = int(round((p.box[0] - left) / space))
                pad = max(0, min(MAX_INDENT + width, target) - width)
                if pad == 0 and prev_end is not None and p.box[0] - prev_end >= 0.6 * space:
                    pad = 1
            elif prev_end is None:
                pad = min(MAX_INDENT, int(round((p.box[0] - left) / space)))
            else:
                gap = p.box[0] - prev_end
                pad = min(MAX_INDENT, int(round(gap / space))) if gap >= 3 * space else 1
            if pad > 0:
                runs.append(Run(" " * pad))
                width += pad
            prev_end = p.box[0] + p.box[2]
            width += int(_cells(p.text))
            styles = _settle(p, snap, bsnap, page)
            for ch, (col, bg, bold) in zip(p.text, styles):
                r = Run(ch, _hex(col) if col else None, _hex(bg) if bg else None, bold)
                if runs and runs[-1].text.strip() and (runs[-1].color, runs[-1].bg, runs[-1].bold) == (r.color, r.bg, r.bold):
                    runs[-1].text += ch
                else:
                    runs.append(r)
        for r in runs:
            if r.color is None and r.text.strip():
                r.color = _hex(fg)
        out.append(tidy(runs))
        if len(out) >= MAX_LINES:
            break
    if not any(out):
        return None
    size = max(6.0, min(72.0, round(em * 72 / dpi * 2) / 2))
    return StyledText(lines=out, bg=_hex(page), fg=_hex(fg), mono=mono, size=size)


def _ink_cols(img, p: _Piece) -> tuple[np.ndarray, int]:
    """Which columns of the piece's rows hold ink (against the piece's own paper), and where they start."""
    x, y, w, h = (int(round(v)) for v in p.box)
    x0, x1 = max(0, x - 4), min(img.shape[1], x + w + 4)
    c = img[max(0, y):y + h, x0:x1]
    if c.size == 0:
        return np.zeros(0, bool), x0
    back = _mode_color(c)
    return (np.abs(c.astype(np.int16) - np.array(back, np.int16)).max(axis=2) > INK).any(axis=0), x0


def _pitch(img, pieces, cell: float) -> float:
    """The width of one letter cell, from long stretches: ink width / letters (the last letter's
    right margin is not ink, hence the small correction)."""
    got = []
    for p in pieces:
        n = _cells(p.text)
        if n < 10 or "  " in p.text:
            continue
        cols, _ = _ink_cols(img, p)
        on = np.flatnonzero(cols)
        if len(on) < 2:
            continue
        v = (on[-1] - on[0] + 1) / (n - 0.15)
        if abs(v - cell) <= 0.2 * cell:
            got.append((n, v))
    if not got:
        return cell
    got.sort()
    return float(np.median([v for _, v in got[len(got) // 2:]]))      # the longer ones are the more exact


def _on_grid(img, p: _Piece, cell: float) -> _Piece:
    """Monospace: letters stand in cells one after the other, so every letter's box is known from
    where the piece's ink starts; the blank between two words is as many spaces as cells it spans
    (the reader gives one space however wide the blank is)."""
    cols, x0 = _ink_cols(img, p)
    on = np.flatnonzero(cols)
    if len(on) == 0:
        return p
    y, h = p.box[1], p.box[3]
    x = float(x0 + on[0])
    text, boxes = [], []
    tokens = re.findall(r"\S+| +", p.text)
    for k, tok in enumerate(tokens):
        if tok[0] == " ":
            if k == 0 or k == len(tokens) - 1:
                continue
            nxt = on[on >= x - x0 - 0.3 * cell]            # where the next word's ink starts
            n = len(tok)
            if len(nxt):
                n = int(round((x0 + nxt[0] - x) / cell))
            n = max(1, min(MAX_INDENT, n))
            text += [" "] * n
            boxes += [None] * n
            x += n * cell
            continue
        start = on[(on >= x - x0 - 0.5 * cell) & (on <= x - x0 + 0.5 * cell)]
        if len(start) and k > 0:                       # keep to the ink: no drift along a long line
            x = 0.5 * x + 0.5 * float(x0 + start[0]) if abs(x0 + start[0] - x) <= 0.35 * cell else x
        for n_, ch in enumerate(tok):
            wd = cell * (2 if _wide(ch) else 1)
            a, b = int(round(x - x0)), int(round(x - x0 + cell))
            if n_ and 0 <= a < b <= len(cols) and not cols[a:b].any() and cols[b:int(b + cell)].any():
                text.append(" ")                       # an empty cell: a space the reader dropped
                boxes.append(None)
                x += cell
            text.append(ch)
            boxes.append((x, y, x + wd, y + h))
            x += wd
    t = "".join(text)
    return _Piece(t, p.box, [None] * len(t), boxes)


def _settle(p: _Piece, snap, bsnap, page) -> list[tuple]:
    """(colour, highlight, bold) for every character: palette colours, thin marks and blanks take
    their neighbours' look, a lone letter that differs from both neighbours is a misreading."""
    chars = p.chars
    n = len(chars)
    cols = [snap.get(c[0]) if c else None for c in chars]
    bgs = [bsnap.get(c[1]) if c else None for c in chars]
    bold = list(p.bold) if len(p.bold) == n else [False] * n
    for arr in (cols, bgs):
        for i in range(n):                             # a single odd one between two equal neighbours
            if 0 < i < n - 1 and arr[i] is not None and arr[i - 1] is not None and arr[i - 1] == arr[i + 1] != arr[i]:
                arr[i] = arr[i - 1]
        last = None
        for i in range(n):
            if arr[i] is None:
                arr[i] = last
            else:
                last = arr[i]
        nxt = None
        for i in range(n - 1, -1, -1):
            if arr[i] is None:
                arr[i] = nxt
            else:
                nxt = arr[i]
    for m in re.finditer(r"[^\W_]+", p.text):         # a word's letters share one colour (it changes
        seen: dict = {}                                 # only at punctuation: quotes, brackets, operators)
        for i in range(m.start(), min(m.end(), n)):
            if cols[i] is not None:
                seen[cols[i]] = seen.get(cols[i], 0) + 1
        if len(seen) > 1:
            best = max(seen, key=seen.get)
            for i in range(m.start(), min(m.end(), n)):
                cols[i] = best
    out = []
    for i in range(n):
        bg = bgs[i]
        if bg is not None and _far(bg, page) <= SAME_BG:
            bg = None
        out.append((cols[i], bg, bold[i]))
    return out


# --- web editors (Confluence) keep only their own palette colours ---------------------------------------
# Atlassian's editor (@atlaskit/adf-schema 57.7.1) drops a pasted text colour or highlight unless it is
# exactly one of these. Each run is written as <span palette><span exact>: Office applies the inner,
# exact colour; Confluence ignores the inner one and keeps the nearest palette colour of the outer.
CONFLUENCE_TEXT = ["#FFFFFF", "#97A0AF", "#EAE6FF", "#6554C0", "#403294", "#B3F5FF", "#00B8D9", "#008DA6",
                   "#ABF5D1", "#36B37E", "#006644", "#FFBDAD", "#FF5630", "#BF2600", "#FFF0B3", "#FFC400",
                   "#FF991F", "#B3D4FF", "#4C9AFF", "#0747A6"]
CONFLUENCE_DEFAULT = "#172B4D"           # its default text colour (no colour written)
CONFLUENCE_HIGHLIGHT = ["#DCDFE4", "#DFD8FD", "#FDD0EC", "#FEDEC8", "#F8E6A0", "#D3F1A7", "#C6EDFB"]
READABLE = 70                            # luma difference from the page a palette colour must keep


def _luma(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _lab(h: str) -> np.ndarray:
    r, g, b = _rgb(h)
    return cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2LAB)[0, 0].astype(float)


def nearest_palette(color: str, page: str, choices=None) -> str | None:
    """The palette colour that looks most like `color` and still reads on the page;
    None when the editor's own default text colour is the closest (nothing to write)."""
    choices = choices or CONFLUENCE_TEXT
    page_l = _luma(page)
    want = _lab(color)
    cands = [c for c in choices if abs(_luma(c) - page_l) >= READABLE]
    if page_l >= 128:
        cands.append(CONFLUENCE_DEFAULT)                 # on a light page the default dark text is an option
    if not cands:
        cands = list(choices)
    best = min(cands, key=lambda c: _distance(_lab(c), want))
    return None if best == CONFLUENCE_DEFAULT else best


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    """Colour difference that also keeps grey grey (a near-white must not turn lavender)."""
    ca, cb = float(np.hypot(a[1] - 128, a[2] - 128)), float(np.hypot(b[1] - 128, b[2] - 128))
    dh = abs(np.arctan2(a[2] - 128, a[1] - 128) - np.arctan2(b[2] - 128, b[1] - 128))
    dh = min(dh, 2 * np.pi - dh)                       # a red stays red, a yellow stays yellow
    return float(np.linalg.norm(a - b)) + 1.5 * abs(ca - cb) + 1.2 * min(ca, cb) * dh


def nearest_highlight(color: str) -> str:
    want = _lab(color)
    return min(CONFLUENCE_HIGHLIGHT, key=lambda c: _distance(_lab(c), want))


# --- out: plain text, HTML, clipboard --------------------------------------------------------------------

def styled_plain(st: StyledText) -> str:
    return "\r\n".join("".join(r.text for r in line).rstrip() for line in st.lines)


_SPACE_BEFORE_SPACE = re.compile(r" (?= )")


def _esc(text: str, at_start: bool) -> str:
    """Escaped for HTML; the indent and runs of blanks survive (browsers and Office fold plain spaces)."""
    lead = len(text) - len(text.lstrip(" ")) if at_start else 0
    body = html.escape(text[lead:], quote=False)
    body = _SPACE_BEFORE_SPACE.sub("&nbsp;", body)
    return "&nbsp;" * lead + body


def styled_html(st: StyledText, keep_bg: bool = True) -> str:
    """One block (a one-cell table: its fill is the page colour everywhere it is pasted), lines
    separated by <br>, every stretch of one look in a <span>. Only text is ever written out."""
    rows = []
    for line in st.lines[:MAX_LINES]:
        parts = []
        for k, r in enumerate(line):
            t = _esc(r.text, at_start=k == 0)
            if not r.text.strip():
                parts.append(t)
                continue
            color = r.color or st.fg
            inner = [f"color:{color}"] + ([f"background-color:{r.bg}"] if r.bg else [])
            t = f"<span style='{';'.join(inner)}'>{t}</span>"            # Office: the exact look
            outer = []                                                  # Confluence: its nearest palette look
            pal = nearest_palette(color, st.bg if keep_bg else "#FFFFFF")
            if pal:
                outer.append(f"color:{pal}")
            if r.bg:
                outer.append(f"background-color:{nearest_highlight(r.bg)}")
            if outer:
                t = f"<span style='{';'.join(outer)}'>{t}</span>"
            if r.bold:
                t = f"<b>{t}</b>"
            parts.append(t)
        rows.append("".join(parts))
    font = MONO_FONT if st.mono else SANS_FONT
    css = (f"color:{st.fg};font-family:{font};font-size:{st.size:g}pt;white-space:nowrap;"
           'vertical-align:top;mso-number-format:"\\@"')
    fill = f' bgcolor="{st.bg}"' if keep_bg else ""
    if keep_bg:
        css = f"background-color:{st.bg};" + css
    return (f"<table style='border-collapse:collapse' cellpadding='8'><tr><td{fill} style='{css}'>"
            + "<br>".join(rows) + "</td></tr></table>")


def styled_payload(st: StyledText, keep_bg: bool = True) -> dict:
    return {UNICODE: styled_plain(st), HTML: cf_html(styled_html(st, keep_bg))}


def redact(st: StyledText) -> StyledText:
    """Personal data hidden (as in plain copies); each stretch keeps its look."""
    from .redact import mask
    lines = []
    for line in st.lines:
        text = "".join(r.text for r in line)
        hidden = mask(text)
        if hidden == text:
            lines.append(line)
        elif len(hidden) == len(text):
            pos, new = 0, []
            for r in line:
                new.append(replace(r, text=hidden[pos:pos + len(r.text)]))
                pos += len(r.text)
            lines.append(new)
        else:
            lines.append([replace(line[0], text=hidden)] if line else [])
    return replace(st, lines=lines)
