"""The exported image must show the text style the user picked (size, bold, italic, lines, font)."""
import numpy as np

from capture_tool.app.render import compose
from capture_tool.core.annotations import Document, Shape


def ink(shape, w=500, h=160):
    """(dark pixel count, bounding box height) of one text shape drawn on white."""
    doc = Document(w, h)
    assert doc.add(shape)
    out = compose(np.full((h, w, 3), 255, np.uint8), doc)
    mask = out.min(axis=2) < 128
    ys = np.nonzero(mask.any(axis=1))[0]
    return int(mask.sum()), (int(ys.max() - ys.min() + 1) if len(ys) else 0), mask


def txt(**kw):
    base = dict(kind="text", points=[(10, 10)], text="Capture 캡처", color="#000000")
    base.update(kw)
    return Shape(**base)


def test_RND_01_font_size_changes_the_drawing(qt_app):
    _, small_h, _ = ink(txt(font_size=16))
    _, big_h, _ = ink(txt(font_size=48))
    assert big_h > small_h * 2


def test_RND_02_bold_uses_more_ink(qt_app):
    regular, _, _ = ink(txt(font_size=30))
    bold, _, _ = ink(txt(font_size=30, bold=True))
    assert bold > regular * 1.15


def test_RND_03_underline_and_strike_draw_lines(qt_app):
    def longest_row(mask):
        return int(mask.sum(axis=1).max())
    _, _, plain = ink(txt(font_size=30))
    _, _, under = ink(txt(font_size=30, underline=True))
    _, _, strike = ink(txt(font_size=30, strike=True))
    assert longest_row(under) > longest_row(plain) * 2
    assert longest_row(strike) > longest_row(plain) * 2


def test_RND_04_italic_changes_the_drawing(qt_app):
    _, _, plain = ink(txt(font_size=30))
    _, _, ital = ink(txt(font_size=30, italic=True))
    assert (plain != ital).sum() > 50


def test_RND_05_font_family_changes_the_drawing(qt_app):
    from PySide6.QtGui import QFontDatabase
    fams = [QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(p))[0]
            for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\times.ttf")]
    _, _, a = ink(txt(text="Capture", font_size=30, font_family=fams[0]))
    _, _, b = ink(txt(text="Capture", font_size=30, font_family=fams[1]))
    assert (a != b).sum() > 100
