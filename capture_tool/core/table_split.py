"""Split text that isn't laid out as a table into rows of cells, by a rule the person picks
in the preview: label/value pairs, 2+ spaces or tabs, commas, one cell per line, or their own
separator."""
from __future__ import annotations

import re

from .ocr import _cy, estimate_tilt, same_row
from .text_table import find_text_table, is_rule_line, normalize_pipes

RULES = ["auto", "pipe", "pair", "spaces", "comma", "line", "custom:|"]
MAX_ROWS = 200
MAX_COLS = 20
_BULLET = re.compile(r"^\s*(?:[•·\-*▪◦●○■□]|\d{1,2}[.)])\s+")
_PAIR = re.compile(r"^([^:：]{1,40}?)\s*[:：]\s*(.*)$")
_SPACES = re.compile(r"\t+|\s{2,}")
_COMMA = re.compile(r",(?!\d{3}(?:\D|$))")      # "1,250,000" stays one cell


def _cells(line: str, rule: str) -> list[str]:
    if rule == "pipe":
        s = line.strip()
        s = s[1:] if s.startswith("|") else s
        s = s[:-1] if s.endswith("|") else s
        return [c.strip() for c in s.split("|")]
    if rule == "pair":
        m = _PAIR.match(line)
        return [m.group(1).strip(), m.group(2).strip()] if m else [line.strip()]
    if rule == "spaces":
        return [c.strip() for c in _SPACES.split(line.strip())]
    if rule == "comma":
        return [c.strip() for c in _COMMA.split(line)]
    if rule.startswith("custom:"):
        sep = rule[7:]
        return [c.strip() for c in line.split(sep)] if sep else [line.strip()]
    return [line.strip()]


def _has_sep(line: str, rule: str) -> bool:
    return len(_cells(line, rule)) > 1


def _auto(lines: list[str]) -> str:
    if sum("|" in l for l in lines) >= max(1, (len(lines) + 1) // 2):
        return "pipe"                                    # a bar on most lines: columns
    found = find_text_table("\n".join(lines))
    if found is not None and found.kind == "pairs":
        return "pair"
    if found is not None:
        return "spaces" if any(_SPACES.search(l) for l in lines) else "comma"
    for rule in ("pair", "spaces", "comma"):
        if sum(_has_sep(l, rule) for l in lines) >= max(1, len(lines) // 2):
            return rule
    return "line"


def split_table(lines: list[str], rule: str = "auto", title_first: bool = True, strip_bullets: bool = True,
                header: bool = False) -> tuple[str | None, list[list[str]]]:
    """(title, rows). The first line becomes the title when it has no separator and the rest
    do; rows are padded to the same width and capped in size."""
    lines = [normalize_pipes(l) for l in (x.rstrip() for x in lines) if l.strip()]
    lines = [l for l in lines if not is_rule_line(l)]
    if not lines:
        return None, []
    if strip_bullets:
        lines = [_BULLET.sub("", l) for l in lines]
    if rule not in RULES and not rule.startswith("custom:"):
        rule = "auto"
    if rule == "auto":
        rule = _auto(lines)
    title = None
    if title_first and len(lines) > 1 and not _has_sep(lines[0], rule) and _has_sep(lines[1], rule):
        title, lines = lines[0].strip(), lines[1:]
    rows = [[c for c in _cells(l, rule)][:MAX_COLS] for l in lines[:MAX_ROWS]]
    if header:
        head = ["항목", "내용"] if rule == "pair" else [f"열 {i + 1}" for i in range(max(len(r) for r in rows))]
        rows = [head] + rows[:MAX_ROWS - 1]
    width = max(len(r) for r in rows)
    return title, [r + [""] * (width - len(r)) for r in rows]


def ocr_row_lines(items: list[tuple[str, tuple]]) -> list[str]:
    """OCR boxes (text, (x, y, w, h)) -> one text line per visual row; pieces far apart are
    joined by a tab (a likely column break), close ones by a space."""
    rows: list[list[tuple[str, tuple]]] = []
    tilt = estimate_tilt([b for _, b in items])
    for text, box in sorted(items, key=lambda it: _cy(it[1], tilt)):
        if rows and same_row(rows[-1][0][1], box, tilt):
            rows[-1].append((text, box))
            continue
        rows.append([(text, box)])
    out = []
    for row in rows:
        row.sort(key=lambda it: it[1][0])
        line = row[0][0]
        for (_, prev), (text, box) in zip(row, row[1:]):
            gap = box[0] - (prev[0] + prev[2])
            line += ("\t" if gap > 0.8 * max(prev[3], box[3]) else " ") + text
        out.append(line)
    return out
