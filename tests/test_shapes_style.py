"""Shapes copied from a capture keep their look: text colour, size and bold, outline-less fills,
diamonds, free text outside shapes, and text the first OCR pass missed inside a coloured shape."""
import cv2
import numpy as np
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from capture_tool.core.drawingml import DShape, drawing_xml
from capture_tool.core.shapes import (Detected, attach_text, detect, find_missed_text, text_boxes_for, text_style,
                                      to_drawing)
from tests.render import _font

DPI = 144                                       # 150 % screen: 2 px per point


def canvas(w=900, h=500, bg="#FFFFFF"):
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor(bg))
    return img


_BOLD = []


def text(img, s, x, y, px, color="#000000", bold=False, box=None):
    if bold and not _BOLD:                          # the real bold face, like Windows apps use
        from PySide6.QtGui import QFontDatabase
        _BOLD.append(QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\malgunbd.ttf"))
    p = QPainter(img)
    f = QFont(_font(10))
    f.setPixelSize(px)
    f.setBold(bold)
    p.setFont(f)
    p.setPen(QColor(color))
    if box:
        p.drawText(QRect(*box), Qt.AlignCenter, s)
    else:
        p.drawText(x, y, s)
    p.end()


def shape(img, kind, box, fill=None, line=None, width=2):
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(fill) if fill else Qt.NoBrush)
    if line:
        pen = p.pen()
        pen.setColor(QColor(line))
        pen.setWidth(width)
        p.setPen(pen)
    else:
        p.setPen(Qt.NoPen)
    x, y, w, h = box
    if kind == "rect":
        p.drawRect(x, y, w, h)
    elif kind == "ellipse":
        p.drawEllipse(x, y, w, h)
    elif kind == "diamond":
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPolygon
        p.drawPolygon(QPolygon([QPoint(x + w // 2, y), QPoint(x + w, y + h // 2), QPoint(x + w // 2, y + h),
                                QPoint(x, y + h // 2)]))
    p.end()


def arr(img):
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
    return a.reshape(img.height(), img.width(), 3)[:, :, ::-1].copy()


def ink_box(a, region):
    """Bounding box of the text pixels in region (what OCR would report, a little padded)."""
    x, y, w, h = region
    c = a[y:y + h, x:x + w].astype(int)
    bg = np.median(np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]]), axis=0)
    m = np.abs(c - bg).max(axis=2) > 60
    ys, xs = np.where(m)
    return (x + xs.min() - 6, y + ys.min() - 8, xs.max() - xs.min() + 12, ys.max() - ys.min() + 16)


def near(h1, h2, tol=40):
    return max(abs(int(h1[i:i + 2], 16) - int(h2[i:i + 2], 16)) for i in (1, 3, 5)) <= tol


@pytest.mark.parametrize("s,px,color,bold,bg,pt", [
    ("요청 접수", 40, "#FFFFFF", True, "#1F5FD1", 20),
    ("검토", 36, "#E8730C", False, "#FFFFFF", 18),
    ("보류 사유", 28, "#C00000", False, "#F2F2F2", 14),
    ("업무 처리 흐름", 56, "#404040", True, "#FFFFFF", 28),
    ("Quality", 32, "#1A1A1A", False, "#FFFFFF", 16),
    ("HELLO", 48, "#2E9E5B", True, "#FFFFFF", 24),
])
def test_STY_01_text_colour_size_and_bold_are_measured(qt_app, s, px, color, bold, bg, pt):
    img = canvas(700, 160, bg)
    text(img, s, 20, 100, px, color, bold)
    a = arr(img)
    st = text_style(a, ink_box(a, (0, 0, 700, 160)), s, DPI)
    assert near(st.color, color), st
    assert st.size == pt, st
    assert st.bold == bold, st


def test_STY_02_shape_text_keeps_its_style_into_powerpoint(qt_app):
    img = canvas()
    shape(img, "rect", (100, 100, 300, 140), fill="#FFFFFF", line="#E8730C", width=4)
    text(img, "검토", 0, 0, 36, "#E8730C", box=(100, 100, 300, 140))
    a = arr(img)
    det = detect(a, text_boxes=[ink_box(a, (110, 110, 280, 120))])
    lines = [("검토", ink_box(a, (110, 110, 280, 120)))]
    rest = attach_text(det, lines, img=a, dpi=DPI)
    assert rest == []
    shapes, _ = to_drawing(det)
    s = next(s for s in shapes if s.text == "검토")
    assert near(s.text_color, "#E8730C") and s.font_size == 18 and not s.bold
    xml = drawing_xml(shapes, [], DPI)
    assert 'sz="1800"' in xml


def test_STY_03_filled_shape_without_outline_gets_no_outline(qt_app):
    img = canvas()
    shape(img, "ellipse", (200, 100, 300, 200), fill="#2E9E5B")
    det = detect(arr(img))
    assert len(det) == 1 and det[0].fill and det[0].stroke is None
    shapes, _ = to_drawing(det)
    assert shapes[0].stroke is None
    assert "<a:ln><a:noFill/></a:ln>" in drawing_xml(shapes, [], DPI)


def test_STY_04_outline_in_a_different_colour_is_kept(qt_app):
    img = canvas()
    shape(img, "rect", (200, 100, 300, 160), fill="#1F5FD1", line="#0B3A8C", width=4)
    d = detect(arr(img))[0]
    assert d.fill and d.stroke and near(d.stroke, "#0B3A8C")


def test_STY_05_diamond_is_recognized_and_linkable(qt_app):
    img = canvas()
    shape(img, "diamond", (300, 100, 240, 160), fill="#F5C518", line="#333333", width=2)
    det = detect(arr(img))
    assert [d.kind for d in det] == ["diamond"]
    shapes, _ = to_drawing(det)
    assert 'prst="diamond"' in drawing_xml(shapes, [], DPI)
    from capture_tool.core.drawingml import DConnector
    xml = drawing_xml(shapes + [DShape("rect", 0, 120, 100, 100)], [DConnector(start=1, end=0)], DPI)
    assert "stCxn" in xml and "endCxn" in xml


def test_STY_06_text_outside_shapes_becomes_text_boxes_with_style(qt_app):
    img = canvas(900, 300)
    text(img, "업무 처리 흐름", 40, 80, 56, "#404040", bold=True)
    text(img, "첫째 줄 설명", 40, 180, 28, "#C00000")
    text(img, "둘째 줄 설명", 40, 222, 28, "#C00000")
    a = arr(img)
    lines = [("업무 처리 흐름", ink_box(a, (0, 0, 900, 110))), ("첫째 줄 설명", ink_box(a, (0, 140, 900, 50))),
             ("둘째 줄 설명", ink_box(a, (0, 192, 900, 50)))]
    boxes = text_boxes_for(lines, a, DPI)
    assert [b.text for b in boxes] == ["업무 처리 흐름", "첫째 줄 설명\n둘째 줄 설명"]      # a paragraph stays together
    assert all(b.kind == "text" and b.fill is None and b.stroke is None for b in boxes)
    shapes, _ = to_drawing(boxes)
    title, para = shapes
    assert title.font_size == 28 and title.bold and near(title.text_color, "#404040")
    assert para.font_size == 14 and not para.bold and near(para.text_color, "#C00000")
    xml = drawing_xml(shapes, [], DPI)
    assert 'wrap="none"' in xml and 'algn="l"' in xml


def test_STY_07_connectors_do_not_glue_to_free_text(qt_app):
    det = [Detected("rect", 100, 100, 100, 80, fill="#FFFFFF", stroke="#000000"),
           Detected("text", 260, 120, 80, 30, text="메모"),
           Detected("arrow", 200, 140, 60, 2, stroke="#000000", points=[(200, 140), (258, 140)])]
    shapes, conns = to_drawing(det)
    assert conns[0].start is None and conns[0].end is None


def test_STY_08_text_missed_inside_a_coloured_shape_is_read_again(qt_app):
    img = canvas()
    shape(img, "ellipse", (300, 100, 300, 200), fill="#2E9E5B")
    text(img, "승인", 0, 0, 44, "#1A1A1A", bold=True, box=(300, 100, 300, 200))
    a = arr(img)
    det = detect(a)                                     # first OCR found nothing: glyph bits look like shapes
    calls = []

    def recognize(crop):
        calls.append(crop.shape)
        h, w = crop.shape[:2]
        return [("승인", (w // 2 - 50, h // 2 - 30, 100, 60))]
    found = find_missed_text(a, det, recognize)
    assert len(calls) == 1 and found and found[0][0] == "승인"
    tx, ty, tw, th = found[0][1]
    assert 300 < tx < 450 and 150 < ty < 230                    # back in whole-image coordinates
    kept = [d for d in det if d.kind == "ellipse" and d.w > 200]
    assert len(kept) == 1                                       # the shape itself stays
    assert all(not (tx <= d.x + d.w / 2 <= tx + tw and ty <= d.y + d.h / 2 <= ty + th)
               for d in det if d not in kept)                  # letter bits taken for shapes are gone


def test_STY_09_missed_text_pass_is_bounded(qt_app):
    det = [Detected("rect", 10 + i * 60, 10, 50, 50, fill="#1F5FD1") for i in range(30)]
    img = np.full((100, 1900, 3), 255, np.uint8)
    for d in det:
        img[d.y:d.y + d.h, d.x:d.x + d.w] = (209, 95, 31)
        img[d.y + 20:d.y + 30, d.x + 10:d.x + 40] = 0          # some ink inside each
    calls = []
    find_missed_text(img, det, lambda c: calls.append(1) or [])
    from capture_tool.core.shapes import MAX_REREAD
    assert len(calls) <= MAX_REREAD


def test_STY_10_blank_coloured_shape_is_not_read_again(qt_app):
    img = canvas()
    shape(img, "rect", (100, 100, 300, 150), fill="#D93025")
    calls = []
    find_missed_text(arr(img), detect(arr(img)), lambda c: calls.append(1) or [])
    assert calls == []


def test_STY_11_shapes_that_already_have_text_are_not_read_twice(qt_app):
    img = canvas()
    shape(img, "rect", (100, 100, 300, 140), fill="#1F5FD1")
    text(img, "요청 접수", 0, 0, 40, "#FFFFFF", bold=True, box=(100, 100, 300, 140))
    a = arr(img)
    box = ink_box(a, (120, 110, 260, 120))
    det = detect(a, text_boxes=[box])
    from capture_tool.core.shapes import attach_found_text
    calls = []
    rest = attach_found_text(a, det, [("요청 접수", box)], lambda c: calls.append(1) or [("요청 접수", (0, 0, 10, 10))], DPI)
    assert calls == [] and rest == []
    assert [d.text for d in det if d.kind == "rect"] == ["요청 접수"]


def test_STY_12_a_doubtful_ocr_line_neither_cuts_the_shape_nor_becomes_its_text(qt_app):
    """OCR read " 인" (score 0.7) with a box covering the whole ellipse: masking that box broke the
    ellipse, and the half-read word would have been its text."""
    from capture_tool.core.shapes import split_doubtful
    img = canvas()
    shape(img, "ellipse", (300, 100, 300, 200), fill="#2E9E5B")
    text(img, "승인", 0, 0, 44, "#1A1A1A", bold=True, box=(300, 100, 300, 200))
    a = arr(img)
    lines = [(" 인", (310, 105, 280, 190), 0.70), ("제목", (20, 400, 80, 30), 0.65), ("확실", (20, 440, 80, 30), 0.99)]
    masks, kept = split_doubtful(lines)
    assert masks == [(20, 440, 80, 30)]                        # only sure lines hide pixels from shape search
    det = detect(a, text_boxes=masks)
    assert [d.kind for d in det if d.w > 200] == ["ellipse"]
    from capture_tool.core.shapes import drop_doubtful_inside
    kept = drop_doubtful_inside(det, lines)
    assert [t for t, _ in kept] == ["제목", "확실"]            # the doubtful word inside the shape is read again


def test_STY_13_without_style_shapes_are_plain_but_keep_size(qt_app):
    det = [Detected("rect", 10, 10, 100, 60, fill="#1F5FD1", stroke="#0B3A8C", text="가",
                    text_color="#FFFFFF", font_size=20, bold=True),
           Detected("text", 10, 100, 100, 30, text="제목", text_color="#FFFFFF", font_size=28, bold=True,
                    fill="#1F1F1E")]
    shapes, _ = to_drawing(det, keep_style=False)
    box, title = shapes
    assert box.fill == "#FFFFFF" and box.stroke == "#000000" and box.text_color == "#000000" and not box.bold
    assert box.font_size == 20 and title.fill is None and title.text_color == "#000000" and title.font_size == 28


def test_STY_14_light_free_text_keeps_its_dark_background_so_it_stays_visible(qt_app):
    img = canvas(600, 200, "#1F1F1E")
    text(img, "어두운 화면 글자", 30, 100, 32, "#F0F0F0")
    a = arr(img)
    boxes = text_boxes_for([("어두운 화면 글자", ink_box(a, (0, 0, 600, 200)))], a, DPI)
    assert boxes[0].fill and near(boxes[0].fill, "#1F1F1E", 12)
    shapes, _ = to_drawing(boxes)
    assert shapes[0].fill and near(shapes[0].fill, "#1F1F1E", 12)
    img2 = canvas(600, 200)
    text(img2, "밝은 화면 글자", 30, 100, 32, "#202020")
    b = arr(img2)
    assert text_boxes_for([("밝은 화면 글자", ink_box(b, (0, 0, 600, 200)))], b, DPI)[0].fill is None
