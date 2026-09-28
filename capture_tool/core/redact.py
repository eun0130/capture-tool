"""Detect personal information in OCR text so it can be masked automatically."""
from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)")
_RRN = re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-?[1-8]\d{6}(?!\d)")
_MOBILE = re.compile(r"(?<![\d+])(?:\+82[-\s]?1[016789]|01[016789])[-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)\(?0(?:2|[3-6][1-5])\)?[-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    kind: str


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def find_pii(text: str) -> list[Match]:
    if not text:
        return []
    found: list[Match] = []
    found += [Match(m.start(), m.end(), "email") for m in _EMAIL.finditer(text)]
    found += [Match(m.start(), m.end(), "card") for m in _CARD.finditer(text)
              if _luhn(re.sub(r"\D", "", m.group()))]
    found += [Match(m.start(), m.end(), "rrn") for m in _RRN.finditer(text)]
    found += [Match(m.start(), m.end(), "phone") for p in (_MOBILE, _LANDLINE) for m in p.finditer(text)]
    found.sort(key=lambda m: (m.start, -(m.end - m.start)))
    out: list[Match] = []
    for m in found:
        if out and m.start < out[-1].end:
            continue
        out.append(m)
    return out


def char_boxes(text: str, box: tuple, spans: list[tuple[int, int]]) -> list[tuple]:
    """Approximate sub-boxes of a text line for character spans (proportional width)."""
    if not text:
        return []
    x, y, w, h = box
    per = w / len(text)
    return [(int(round(x + s * per)), y, int(round((e - s) * per)), h) for s, e in spans]


def line_pii_boxes(text: str, box: tuple) -> list[tuple]:
    return char_boxes(text, box, [(m.start, m.end) for m in find_pii(text)])


def mask_word_boxes(words: list[tuple[str, tuple]]) -> list[tuple]:
    """words: OCR words of one line in reading order -> boxes of words that hold PII."""
    if not words:
        return []
    spans = []
    pos = 0
    for text, _ in words:
        spans.append((pos, pos + len(text)))
        pos += len(text) + 1
    line = " ".join(t for t, _ in words)
    hits = find_pii(line)
    boxes = []
    for (s, e), (_, box) in zip(spans, words):
        if any(s < m.end and m.start < e for m in hits):
            boxes.append(box)
    return boxes


def mask(text: str) -> str:
    """Phone numbers, e-mail, resident numbers and card numbers replaced by * (spaces kept)."""
    out = list(text)
    for m in find_pii(text):
        for i in range(m.start, m.end):
            if not out[i].isspace():
                out[i] = "*"
    return "".join(out)
