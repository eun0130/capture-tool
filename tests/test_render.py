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


# --- v0.3.5: text background, freeform clip -----------------------------------------------

def test_RND_06_text_background_is_painted_behind_the_text(qt_app):
    doc = Document(400, 120)
    doc.add(txt(font_size=30, bg="#FFEC99"))
    out = compose(np.full((120, 400, 3), 255, np.uint8), doc)
    yellow = (np.abs(out.astype(int) - (0x99, 0xEC, 0xFF)).sum(axis=2) < 30)
    assert yellow.sum() > 500                              # a box of the background color
    ys, xs = np.nonzero(yellow)
    assert xs.min() <= 12 and ys.min() <= 12                 # starts at the text position
    assert (out.min(axis=2) < 100).sum() > 100               # the text is still drawn on it


def test_RND_07_no_background_leaves_the_capture_alone(qt_app):
    doc = Document(400, 120)
    doc.add(txt(font_size=30))
    out = compose(np.full((120, 400, 3), 255, np.uint8), doc)
    assert (np.abs(out.astype(int) - (0x99, 0xEC, 0xFF)).sum(axis=2) < 30).sum() == 0


def test_RND_08_clip_returns_transparent_cut_out(qt_app):
    doc = Document(200, 100)
    doc.add(Shape(kind="rect", points=[(0, 0), (199, 99)], color="#000000", width=6))
    doc.add(Shape(kind="clip", points=[(20, 10), (120, 10), (70, 90)]))
    out = compose(np.full((100, 200, 3), 128, np.uint8), doc)
    assert out.shape == (81, 101, 4)
    assert out[78, 2, 3] == 0 and out[20, 50, 3] == 255


def test_RND_09_clip_shape_itself_is_not_drawn(qt_app):
    doc = Document(200, 100)
    doc.add(Shape(kind="clip", points=[(0, 0), (199, 0), (199, 99), (0, 99)], color="#000000"))
    out = compose(np.full((100, 200, 3), 128, np.uint8), doc)
    assert (out[:, :, :3] == 128).all()
