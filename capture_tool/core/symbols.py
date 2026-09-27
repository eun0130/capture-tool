"""Symbols for the text tool's picker. Every one has a glyph in Malgun Gothic (the default
font), so it renders the same in the capture and in PowerPoint; color emoji are left out
because they turn into boxes in saved images."""
from __future__ import annotations

SYMBOLS: list[tuple[str, str]] = [
    ("도형", "★☆●○◎■□▲△▼▽◆◇♥♡♠♣"),
    ("체크", "✓✔✕✗☑☐※"),
    ("화살표", "→←↑↓↔↕⇒⇐⇔↗↘↙↖➔"),
    ("번호", "①②③④⑤⑥⑦⑧⑨⑩㉠㉡㉢㉣"),
    ("수학", "±×÷≠≤≥≒∞∴∵√∑°℃%‰"),
    ("괄호", "「」『』【】《》〈〉"),
    ("기타", "•·…☎♪☞☜㈜№™©®€¥₩"),
]


def all_symbols() -> list[str]:
    return [ch for _, chars in SYMBOLS for ch in chars]
