"""Symbols offered by the text tool's symbol picker."""
from capture_tool.core.symbols import SYMBOLS, all_symbols


def test_SYM_01_enough_symbols_grouped_and_unique():
    flat = all_symbols()
    assert len(flat) >= 60 and len(flat) == len(set(flat))
    assert {"★", "✓", "→", "①", "※"} <= set(flat)
    assert all(isinstance(name, str) and chars for name, chars in SYMBOLS)


def test_SYM_02_no_color_emoji_or_control_characters():
    for s in all_symbols():
        assert len(s) == 1 and ord(s) <= 0xFFFF            # BMP only: renders in Malgun Gothic / PPT
        assert s.isprintable() and not s.isspace()
        assert ord(s) != 0xFE0F


def test_SYM_03_every_symbol_has_a_glyph_in_the_default_font(qt_app):
    import os
    import pytest
    from PySide6.QtGui import QRawFont
    path = r"C:\Windows\Fonts\malgun.ttf"
    if not os.path.exists(path):
        pytest.skip("Malgun Gothic not installed")
    f = QRawFont(path, 20)
    assert [s for s in all_symbols() if not f.supportsCharacter(s)] == []   # no tofu boxes
