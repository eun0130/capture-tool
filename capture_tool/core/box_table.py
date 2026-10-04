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
import unicodedata

import cv2
import numpy as np

from .table_capture import CapturedTable, TableStyle, join_wrapped

INK = 40                 # grey-level difference from the background that counts as ink
RULE_SHARE = 0.5         # a horizontal rule covers at least this share of the width
MIN_RULES = 3            # header + one row at least
GLYPH_GAP = 4            # px; pieces of one letter / one Latin word are closer than this
LATIN_BREAK = 7          # px; a wider gap after a Latin word is a space
BARS = "│|┃ㅣ"
PUNCT = "\"'“”‘’()[]{}·,.:;!?"
PUNCT_BREAK = 0.75       # next to punctuation: a space only for a gap this share of a syllable pitch


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
NORMAL_GAP = 0.5         # ordinary (not spread-out) text: a gap this share of the letter height is a space
SENTENCE_GAP = 0.25      # after "." / "·": a gap this wide ends the sentence (list dots like "엑셀·PPT" are tight)
SPREAD_SHARE = 0.6       # Korean read mostly syllable by syllable = a terminal font spreading letters apart
SPACE_RATIO = 1.6        # a space: blank this many times the widest usual gap inside words (90th percentile) ...
SPACE_EXTRA = 3          # ... and at least this many px more


def _bar_pixels(ink: np.ndarray, min_run: int) -> np.ndarray:
    """Pixels of vertical strokes at least min_run tall (the │ bars, shifted or not); letters
    touching a bar keep their own pixels."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, min_run)))
    bars = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, k)
    return cv2.dilate(bars, np.ones((1, 3), np.uint8)) > 0


def _arrows_between(clean: np.ndarray, line: list, bgv: int) -> list:
    """Arrows the reader skipped entirely: drawn in the gap between two words of a line."""
    from .ocr import arrow_kind
    out = []
    for (t, b, *_), (t2, b2, *_) in zip(line, line[1:]):
        x0, x1 = int(b[2]) + 1, int(b2[0]) - 1
        y0, y1 = int(min(b[1], b2[1])), int(max(b[3], b2[3]))
        if x1 - x0 < 6:
            continue
        crop = clean[max(0, y0):y1, x0:x1]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(int)
        ink = (np.abs(g - bgv) > 60).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        for k in range(1, n):
            x, y, w, h, _a = (int(v) for v in st[k])
            kind = arrow_kind(lab[y:y + h, x:x + w] == k) if w >= 6 and h <= 0.7 * ink.shape[0] else None
            if kind:
                out.append((kind, (x0 + x, y0 + y, x0 + x + w, y0 + y + h)))
    return out


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
    return 1e9            # two whole words: the reader split them at a space (normal, not spread-out text)


def _blank_runs(cols: np.ndarray) -> list[int]:
    """Widths of the blank stretches between the first and the last ink column."""
    if not cols.any():
        return []
    first, last = int(np.argmax(cols)), len(cols) - int(np.argmax(cols[::-1]))
    runs, start = [], None
    for x in range(first, last):
        if not cols[x] and start is None:
            start = x
        elif cols[x] and start is not None:
            runs.append(x - start)
            start = None
    return runs


def _ink_gap(ink: np.ndarray, a, b) -> int:
    """Blank columns between the last ink of word a and the first ink of word b (their own line)."""
    y0, y1 = int(min(a[1][1], b[1][1])), int(max(a[1][3], b[1][3]))
    x0, x1 = int(a[1][0]), int(b[1][2])
    if x1 <= x0 or y1 <= y0:
        return int(b[1][0] - a[1][2])
    cols = ink[max(0, y0):y1, max(0, x0):x1].any(axis=0)
    mid = int(b[1][0]) - x0
    left, right = cols[:max(1, int(a[1][2]) - x0)], cols[max(0, mid):]
    last = len(left) - int(np.argmax(left[::-1])) if left.any() else len(left)
    first = mid + (int(np.argmax(right)) if right.any() else 0)
    return first - last


def _space_threshold(ink: np.ndarray, lines: list[list]) -> float | None:
    """Blank wider than this between two words is a space: clearly wider than the gaps the reader
    found inside its words (between letters / syllables) on this very table - so it fits any font."""
    inner = []
    for ln in lines:
        for w in ln:
            x0, y0, x1, y1 = (int(v) for v in w[1])
            if len(w[0].strip()) >= 2 and x1 - x0 > 4 and y1 > y0:
                inner += [r for r in _blank_runs(ink[max(0, y0):y1, max(0, x0):x1].any(axis=0)) if r >= 2]
    if len(inner) < 5:
        return None
    g = float(np.percentile(inner, 90))
    return max(SPACE_RATIO * g, g + SPACE_EXTRA)


def _join_runs(words: list, step: float, spread: bool = True, char_h: float = 20.0,
               gap_of=None, space_px: float | None = None) -> list[list]:
    """Words of one cell, left to right -> [[text, colour], ...] (the text starting with its space).
    Between Korean syllables a space only where the gap is clearly wider than between the letters
    of a word (step: the usual gap)."""
    pieces: list[list] = []
    prev = None
    for w in words:
        t, b = w[0].strip(), w[1]
        color = w[2] if len(w) > 2 else None
        if not t or all(ch in BARS for ch in t):
            continue
        if prev is None:
            pieces.append([t, color])
            prev = (t, b)
            prev_w = w
            continue
        pt, pb = prev
        gap = b[0] - pb[2]
        last = pieces[-1][0]
        if space_px is not None and not spread:              # blank clearly wider than inside words
            space = gap_of(prev_w, w) > space_px
            if space and last[-1:] == "·" and t[:1] not in PUNCT:
                pieces[-1][0] = last[:-1] + "."                  # a full stop read as "·"
        elif last[-1:] in ("·", ".") and gap > SENTENCE_GAP * char_h and t[:1] not in PUNCT:
            pieces[-1][0] = last[:-1] + "."                      # a full stop (read as "·") and a space
            space = True
        elif not spread:                                         # ordinary text: a space is a visible gap
            space = gap > NORMAL_GAP * char_h
        elif _is_hangul(pt[-1:]) and _is_hangul(t[:1]):
            space = _pitch(pt, pb, t, b) > HANGUL_BREAK * step
        elif len(pt) > 1 and len(t) > 1:
            space = True                                         # two whole words
        elif (pt[-1:] in PUNCT or t[:1] in PUNCT) and step < 1e8 and (
                _is_hangul(pt.rstrip(PUNCT)[-1:]) or _is_hangul(t.lstrip(PUNCT)[:1])):
            space = gap > PUNCT_BREAK * step                     # quotes cling to a word
        else:
            space = gap > LATIN_BREAK
        pieces.append([(" " if space else "") + t, color])
        prev = (t, b)
        prev_w = w
    for p in pieces:
        p[0] = p[0].replace("“", '"').replace("”", '"')
        p[0] = re.sub(r"(?<=[\uac00-\ud7a3A-Za-z0-9)\]\"'])·(?=\s|$)", ".", p[0])   # a full stop read as "·"
    # merge neighbours of the same colour
    out: list[list] = []
    for p in pieces:
        if out and out[-1][1] == p[1]:
            out[-1][0] += p[0]
        else:
            out.append(list(p))
    if out:
        out[0][0] = out[0][0].lstrip()
    return out


def _join(words: list, step: float, spread: bool = True, char_h: float = 20.0) -> str:
    return _strip_bars("".join(p[0] for p in _join_runs(words, step, spread, char_h)))


def _word_color(img: np.ndarray, gray: np.ndarray, bgv: int, box):
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    d = np.abs(gray[y0:y1, x0:x1] - bgv)
    if (d > INK).sum() < 4:
        return None
    m = d >= np.percentile(d[d > INK], 70)                        # the letters' cores, not their blended edges
    return tuple(int(v) for v in np.median(img[y0:y1, x0:x1][m], axis=0))


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
    if len(cols) < 2 or len(cols) > 16:            # one column is a table too (the rest cut off)
        return None
    same = gray == bgv
    bg = tuple(int(v) for v in np.median(img[same], axis=0))
    ncol = len(cols) - 1
    clean = img.copy()
    clean[_bar_pixels(ink, int(round(BAR_RUN * dpi / 96)))] = bg      # the │ bars never reach the reader
    for y in rules:
        clean[max(0, y - 3):y + 4] = bg                                  # nor the ─ rules
    words = [(t, b, _word_color(img, gray, bgv, b)) for t, b in read_words(clean)]   # one pass, whole table
    bands = []
    steps = []
    for top, bot in zip(rules, rules[1:]):
        y0, y1 = top + 3, bot - 2
        if y1 - y0 < 8:
            continue
        mine = [w for w in words if y0 <= (w[1][1] + w[1][3]) / 2 < y1]
        lines = [sorted(ln + _arrows_between(clean, ln, bgv), key=lambda w: w[1][0]) for ln in _visual_lines(mine)]
        for ln in lines:
            for (t, b, *_), (t2, b2, *_) in zip(ln, ln[1:]):
                if _is_hangul(t.strip()[-1:]) and _is_hangul(t2.strip()[:1]):
                    p = _pitch(t, b, t2, b2)
                    if p < 1e8:
                        steps.append(p)
        bands.append((y0, y1, lines))
    if not bands:
        return None
    step = float(np.percentile(steps, 25)) if steps else 1e9
    hangul = [w[0].strip() for w in words if _is_hangul(w[0].strip()[:1])]
    spread = bool(hangul) and sum(1 for t in hangul if len(t) == 1) >= SPREAD_SHARE * len(hangul)
    char_h = float(np.median([w[1][3] - w[1][1] for w in words])) * 0.6 if words else 20.0
    ink_clean = np.abs(cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY).astype(int) - bgv) > INK
    space_px = None if spread else _space_threshold(ink_clean, [ln for _, _, lines in bands for ln in lines])
    gap_of = lambda a, b: _ink_gap(ink_clean, a, b)            # noqa: E731
    bar_px = _bar_pixels(ink, int(round(BAR_RUN * dpi / 96)))
    rows: list[list[str]] = []
    run_cells: dict = {}
    heights = []
    for y0, y1, lines in bands:
        cells: list[list] = [[] for _ in range(ncol)]
        last = None
        for ln in lines:
            ly0 = int(min(b[1] for _, b, *_ in ln))
            ly1 = int(max(b[3] for _, b, *_ in ln))
            heights.append(ly1 - ly0)
            left = bar_px[max(0, ly0 - 2):ly1 + 2, max(0, cols[0] - 2):cols[0] + 3].any(axis=1).mean() >= 0.6
            if not left and last is not None:              # wrapped by the terminal: back to its cell
                cells[last].append(("\r", None))            # (the window's edge, not the column's, cut it)
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
        for c, ws in enumerate(cells):
            parts, cur, window = [], [], False
            for w in ws + [("\n", None)]:
                if w[0] in ("\n", "\r"):
                    if cur:
                        runs_ = _join_runs(cur, step, spread, char_h, gap_of, space_px)
                        if runs_:
                            parts.append((runs_, max(x[1][2] for x in cur), window))
                    cur, window = [], w[0] == "\r"
                else:
                    cur.append(w)
            limit = max((r_ for _, r_, _w in parts), default=0)
            flat_runs: list[list] = []
            prev_text, prev_right = "", None
            for k, (part, right, by_window) in enumerate(parts):
                head = "".join(t_ for t_, _ in part)
                if k:                                       # a wrapped line: cut mid-word, or at a space?
                    edge = img.shape[1] if by_window else limit
                    glued = join_wrapped([(prev_text, prev_right), (head, right)], edge,
                                         char_h / 0.6)
                    sep = "" if glued == prev_text.strip() + head.strip() else " "
                else:
                    sep = ""
                for j_, (txt, col) in enumerate(part):
                    flat_runs.append([(sep + txt) if not j_ else txt, col])
                prev_text, prev_right = head, right
            text = _strip_bars("".join(t for t, _ in flat_runs))
            row.append(text)
            run_cells[(len(rows), c)] = flat_runs
        rows.append(row)
    if len(rows) < 2 or sum(1 for r in rows for c in r if c) < len(rows):
        return None
    fg_mask = ink.copy()
    for y in rules:
        fg_mask[max(0, y - 2):y + 3] = False
    fg_mask[_bar_pixels(ink, int(round(BAR_RUN * dpi / 96)))] = False
    cols_seen = [w[2] for w in words if w[2] is not None]
    if cols_seen:                                             # the words' own colour (edges blend into the page)
        text_c = tuple(int(v) for v in np.median(np.array(cols_seen), axis=0))
    else:
        text_c = np.median(img[fg_mask], axis=0) if fg_mask.any() else (0, 0, 0)
    # a 1 px bright rule with its blended neighbours looks mid-grey: use what the eye sees
    band = np.stack([img[max(0, y - 1):y + 2].mean(axis=0) for y in rules])
    on = np.abs(band.mean(axis=2) - bgv) > INK / 2
    rule_c = np.median(band[on], axis=0) if on.any() else text_c
    size = max(8.0, min(20.0, round(float(np.median(heights)) * 0.62 * 72 / dpi * 2) / 2)) if heights else 11.0   # word boxes ~1.6x the font
    style = TableStyle(_hex(bg), _hex(bg), _hex(text_c), _hex(text_c), _hex(rule_c), True, size)
    widths = [(b - a) * 72 / dpi for a, b in zip(cols, cols[1:])]
    t = CapturedTable(rows, (cols[0], rules[0], cols[-1] - cols[0], rules[-1] - rules[0]), [], style, widths)
    t.cut_edge = _cut_at_edge(ink, rules)
    t.runs = _colour_runs(run_cells, text_c)
    return t


def _colour_runs(run_cells: dict, main) -> dict:
    """Cells with words in another colour than the table's text: [(text, "#RRGGBB" | None)]."""
    out = {}
    for key, runs in run_cells.items():
        far = [r for r in runs if r[1] is not None and max(abs(a - b) for a, b in zip(r[1], main)) > 60]
        if not far:
            continue
        merged: list[list] = []                                  # [text, colour or None, raw colour]
        for txt, col in runs:
            own = col is not None and max(abs(a - b) for a, b in zip(col, main)) > 60
            if merged and ((not own and merged[-1][1] is None) or (own and merged[-1][2] is not None and
                                                                  max(abs(a - b) for a, b in zip(col, merged[-1][2])) <= 40)):
                merged[-1][0] += txt                             # same colour (or near enough)
            else:
                merged.append([txt, _hex(col) if own else None, col if own else None])
        if merged:
            merged[0][0] = merged[0][0].lstrip()
            out[key] = [(t_, c_) for t_, c_, _raw in merged]
    return out


def _cut_at_edge(ink: np.ndarray, rules: list[int]) -> bool:
    """Letters touching the capture's left or right edge between the rules: cut by the capture."""
    rows = np.ones(ink.shape[0], bool)
    rows[:rules[0] + 3] = False
    rows[rules[-1] - 2:] = False
    for y in rules:
        rows[max(0, y - 3):y + 4] = False
    for x in (0, ink.shape[1] - 1):
        col = ink[rows, x]
        if col.sum() >= 3 and col.mean() < 0.6:                 # some ink, not a full-height border
            return True
    return False
