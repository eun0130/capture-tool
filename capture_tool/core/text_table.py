"""Text laid out like a table (an AI answer with | columns, tabs, space-aligned columns or
"항목: 값" lines) -> rows of cells for Excel / PowerPoint."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_ROWS = 200            # PowerPoint fills a table cell by cell; keep it quick
MAX_COLS = 20
MIN_PAIRS = 3             # "label: value" lines needed before they count as a table

# characters OCR gives for a column bar: box drawing, broken bar, full-width bar, the Korean vowel ㅣ
_BAR_ALWAYS = str.maketrans({c: "|" for c in "│┃¦｜"})
_BAR_LONE = re.compile(r"(?<=\s)[lI](?=\s)|(?<![\w가-힣])ㅣ|ㅣ(?![\w가-힣])|(?<=\d)ㅣ")
_RULE_CHARS = set("-−–—―…·.:=_~ 	|+")        # what a "---" row turns into when read from a picture
_SEPARATOR = re.compile(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*")


def normalize_pipes(line: str) -> str:
    """OCR look-alikes of the column bar become "|": box-drawing bars always; the Korean vowel ㅣ
    when it stands alone or after a digit; a lone l / I only on a line that already has a bar."""
    s = line.translate(_BAR_ALWAYS)
    if "|" in s:
        s = _BAR_LONE.sub("|", s)
    elif "ㅣ" in s and s.count("ㅣ") >= 2:
        s = s.replace("ㅣ", "|")
    return s


def is_rule_line(line: str) -> bool:
    """A horizontal rule ("|---|---|", "=====", or its OCR mangling "|-−|-……-|"): never data."""
    s = line.strip()
    if len(s) < 2 or not s or set(s) - _RULE_CHARS:
        return False
    return sum(ch not in " 	|" for ch in s) >= 2        # "|" alone or "-" alone is a cell, not a rule
_PAIR = re.compile(r"\s*(?:[•·\-*]|\d{1,2}[.)])?\s*([^:：|\t]{1,30}?)\s*[:：]\s+(\S.*)")
_SPACES = re.compile(r"\S(?:.*?\S)?(?=\s{2,}|$)")


@dataclass
class TextTable:
    rows: list[list[str]]
    kind: str                 # "grid" (columns), "pairs" (label: value lines)
    cut: bool = False         # trimmed to MAX_ROWS x MAX_COLS


def _clean(cell: str) -> str:
    cell = re.sub(r"<[^>]{1,20}>", "", cell)
    cell = cell.replace("**", "").replace("__", "").replace("`", "")
    return cell.replace("\\|", "|").strip()


def _pipe_cells(line: str) -> list[str] | None:
    if "|" not in line.replace("\\|", ""):
        return None
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells = re.split(r"(?<!\\)\|", s)
    return [_clean(c) for c in cells] if len(cells) >= 2 else None


def _blocks(lines: list[str], parse) -> list[list[list[str]]]:
    """Runs of consecutive lines that `parse` turns into cells (None ends a run)."""
    out, cur = [], []
    for line in lines + [""]:
        cells = parse(line) if line.strip() else None
        if cells is None:
            if cur:
                out.append(cur)
            cur = []
        elif cells:                                   # [] = skip this line, keep the run
            cur.append(cells)
    return out


def _pipe(line: str):
    line = normalize_pipes(line)
    if (_SEPARATOR.fullmatch(line) and "-" in line) or ("|" in line and is_rule_line(line)):
        return []
    return _pipe_cells(line)


def _tabs(line: str):
    cells = [_clean(c) for c in line.split("\t")]
    return cells if len(cells) >= 2 else None


def _aligned(line: str):
    cells = [_clean(m.group(0)) for m in _SPACES.finditer(line)]
    return cells if len(cells) >= 2 else None


def _pair(line: str):
    m = _PAIR.fullmatch(line)
    if not m or "://" in line[:m.end(1) + 3]:
        return None
    return [_clean(m.group(1)), _clean(m.group(2))]


def _square(rows: list[list[str]]) -> tuple[list[list[str]], bool]:
    width = max(len(r) for r in rows)
    cut = len(rows) > MAX_ROWS or width > MAX_COLS
    width = min(width, MAX_COLS)
    rows = [(r + [""] * width)[:width] for r in rows[:MAX_ROWS]]
    return rows, cut


def find_text_table(text: str) -> TextTable | None:
    """The biggest table-shaped block in `text`, or None for ordinary prose / bullet lists."""
    if not text or not text.strip():
        return None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found: list[tuple[list[list[str]], str]] = []
    for parse, kind, min_rows in [(_pipe, "grid", 2), (_tabs, "grid", 2), (_aligned, "grid", 3),
                                  (_pair, "pairs", MIN_PAIRS)]:
        for block in _blocks(lines, parse):
            if len(block) < min_rows:
                continue
            if kind == "grid" and parse is _aligned and len({len(r) for r in block}) != 1:
                continue                                  # space-aligned columns must agree
            if not any(c for r in block for c in r):
                continue
            found.append((block, kind))
    if not found:
        return None
    block, kind = max(found, key=lambda b: (sum(len(r) for r in b[0]), b[1] == "grid"))
    rows, cut = _square(block)
    return TextTable(rows, kind, cut)
