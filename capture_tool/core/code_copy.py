"""코드로 복사: the lines read from a screenshot of code (an editor, GitHub, a diff view) turned
into code that pastes and runs - the editor's line numbers and the diff gutter (+ / -) left
out, the indentation put back from where each line's first word sits on screen, typographic
quotes and full-width signs turned into their code characters."""
from __future__ import annotations

import re

from .ocr import OcrLine, estimate_tilt, reading_order, same_row

_NUMBER = re.compile(r"^\d{1,5}[:|]?$")
_SIGN = {"+", "-"}
_CHARS = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'",
                        "«": '"', "»": '"', "…": "...", " ": " "})


class _Row:
    """One visual row: its word pieces (text, x0, x1) left to right - the reader's word boxes when
    it gave them, else the line's words placed along its box in proportion (the box starts where
    the first letter does, which is what indentation needs)."""

    def __init__(self, lines: list[OcrLine]):
        self.pieces: list[tuple[str, float, float]] = []
        for l in sorted(lines, key=lambda l: l.box[0]):
            got = []
            for w in l.words or ():
                try:
                    t, (x0, _, x1, _) = str(w[0]), w[1]
                    if t:
                        got.append((t, float(x0), float(x1)))
                except (TypeError, ValueError, IndexError):
                    continue
            self.pieces.extend(got or _spread(l))
        self.strip = 0                       # leading pieces that are gutter, not code
        self.numbered = False

    def first(self) -> str:
        return self.pieces[self.strip][0] if self.strip < len(self.pieces) else ""

    def code_x(self) -> float | None:
        return self.pieces[self.strip][1] if self.strip < len(self.pieces) else None

    def char_width(self) -> float | None:
        ws = [(x1 - x0) / len(t) for t, x0, x1 in self.pieces if len(t) >= 3 and x1 > x0]             or [(x1 - x0) / len(t) for t, x0, x1 in self.pieces if x1 > x0]      # short tokens only: still a width
        return sum(ws) / len(ws) if ws else None


def _spread(l: OcrLine) -> list[tuple[str, float, float]]:
    """A line without word boxes: its words laid along the box, each as wide as its share of the
    characters."""
    text = l.text.strip()
    if not text:
        return []
    x, w = float(l.box[0]), float(l.box[2])
    per = w / max(1, len(text))
    out, i = [], 0
    for t in text.split(" "):
        if t:
            out.append((t, x + i * per, x + (i + len(t)) * per))
        i += len(t) + 1
    return out


def _rows(lines: list[OcrLine]) -> list[_Row]:
    ordered = [l for l in reading_order(lines) if l.text]
    tilt = estimate_tilt([l.box for l in ordered])
    groups: list[list[OcrLine]] = []
    for l in ordered:
        if groups and same_row(groups[-1][0].box, l.box, tilt):
            groups[-1].append(l)
        else:
            groups.append([l])
    return [_Row(g) for g in groups]


def _strip_numbers(rows: list[_Row]) -> None:
    """A line-number column: most rows start with a small integer, mostly going up."""
    starts = [r.first() for r in rows]
    nums = [int(re.sub(r"\D", "", s)) for s in starts if _NUMBER.match(s)]
    if len(nums) < max(2, 0.6 * len(rows)):
        return
    if sum(1 for a, b in zip(nums, nums[1:]) if b > a) < 0.6 * (len(nums) - 1):
        return
    for r in rows:
        if _NUMBER.match(r.first()):
            r.strip += 1
            r.numbered = True


def _strip_signs(rows: list[_Row]) -> None:
    """A diff gutter: lone + / - at the start of the code column. A YAML or Markdown list ("- one")
    has only dashes and never a plus: it is kept."""
    signs = [r.first() for r in rows if r.first() in _SIGN]
    if not signs or "+" not in signs:
        return
    for r in rows:
        if r.first() in _SIGN:
            r.strip += 1


def _indent(rows: list[_Row]) -> list[str]:
    """Spaces before each row's code, from how far right its first word starts compared with the
    leftmost code of the block, measured in this screenshot's own character width."""
    block = [r for r in rows if r.numbered] or rows      # the margin is the numbered code's, not a status line's
    xs = [r.code_x() for r in block if r.code_x() is not None]
    widths = [w for r in rows for w in [r.char_width()] if w]
    if not xs or not widths:
        return ["" for _ in rows]
    left, cw = min(xs), sorted(widths)[len(widths) // 2]
    out = []
    for r in rows:
        x = r.code_x()
        out.append(" " * max(0, int(round((x - left) / cw))) if x is not None else "")
    return out


def code_text(lines: list[OcrLine]) -> str:
    """The code in the recognized lines, one row per line."""
    rows = [r for r in _rows(lines) if r.pieces]
    if not rows:
        return ""
    _strip_numbers(rows)
    _strip_signs(rows)
    indents = _indent(rows)
    out = []
    for r, ind in zip(rows, indents):
        body = " ".join(t for t, _, _ in r.pieces[r.strip:])
        out.append((ind + body).rstrip())
    return "\n".join(out).translate(_CHARS).translate(_fullwidth())


def _fullwidth() -> dict:
    """Full-width ASCII (U+FF01-FF5E) to ASCII - an IME or a web page sometimes shows ＋ ＝ （ ）."""
    return {c: chr(c - 0xFF01 + 0x21) for c in range(0xFF01, 0xFF5F)}
