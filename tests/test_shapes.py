import cv2
import numpy as np
import pytest

from capture_tool.core.shapes import Detected, attach_text, detect, to_drawing
from tests import synth


def iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def cdist(h1, h2):
    a, b = np.array(synth.bgr(h1), float), np.array(synth.bgr(h2), float)
    return float(np.linalg.norm(a - b))


def box(d):
    return (d.x, d.y, d.w, d.h)


def only(img, **kw):
    found = detect(img, **kw)
    assert len(found) == 1, found
    return found[0]


def test_SHP_01_rect():
    img = synth.canvas()
    gt = synth.rect(img, 100, 80, 200, 120, fill="#F1F3F5")
    d = only(img)
    assert d.kind == "rect"
    assert iou(box(d), (gt.x, gt.y, gt.w, gt.h)) >= 0.9


def test_SHP_02_round_rect():
    img = synth.canvas()
    synth.rect(img, 100, 80, 200, 90, fill="#F1F3F5", radius=20)
    assert only(img).kind == "roundRect"


def test_SHP_02b_pill_is_round_rect():
    img = synth.canvas()
    synth.rect(img, 100, 80, 200, 64, fill="#F1F3F5", radius=32)
    assert only(img).kind == "roundRect"


@pytest.mark.parametrize("w,h", [(150, 150), (220, 110)])
def test_SHP_03_ellipse(w, h):
    img = synth.canvas()
    synth.ellipse(img, 100, 80, w, h, fill="#D0EBFF")
    assert only(img).kind == "ellipse"


def test_SHP_04_triangle():
    img = synth.canvas()
    synth.triangle(img, 100, 80, 180, 140, fill="#FFF3BF")
    assert only(img).kind == "triangle"


@pytest.mark.parametrize("pts", [(50, 200, 400, 200), (100, 50, 100, 300), (60, 60, 360, 260)])
def test_SHP_05_line(pts):
    img = synth.canvas()
    synth.line(img, *pts)
    d = only(img)
    assert d.kind == "line"
    ends = sorted(d.points)
    gt = sorted([(pts[0], pts[1]), (pts[2], pts[3])])
    for (x, y), (gx, gy) in zip(ends, gt):
        assert abs(x - gx) <= 5 and abs(y - gy) <= 5


@pytest.mark.parametrize("pts", [(50, 200, 400, 200), (400, 200, 50, 200), (100, 300, 100, 50), (60, 60, 360, 260)])
def test_SHP_06_arrow_direction(pts):
    img = synth.canvas()
    synth.line(img, *pts, arrow=True)
    d = only(img)
    assert d.kind == "arrow"
    (sx, sy), (ex, ey) = d.points
    assert abs(ex - pts[2]) <= 6 and abs(ey - pts[3]) <= 6  # end = arrow head
    assert abs(sx - pts[0]) <= 6 and abs(sy - pts[1]) <= 6


def test_SHP_07_colors():
    img = synth.canvas()
    synth.rect(img, 100, 80, 200, 120, fill="#D0EBFF", stroke="#1971C2", t=3)
    d = only(img)
    assert cdist(d.fill, "#D0EBFF") <= 12
    assert cdist(d.stroke, "#1971C2") <= 12


def test_SHP_07b_no_fill():
    img = synth.canvas()
    synth.rect(img, 100, 80, 200, 120, fill=None, stroke="#E03131", t=3)
    d = only(img)
    assert d.fill is None
    assert cdist(d.stroke, "#E03131") <= 12


def test_SHP_08_many_shapes():
    img = synth.canvas(900, 400)
    synth.rect(img, 20, 40, 150, 64, fill="#F1F3F5")
    synth.ellipse(img, 240, 40, 150, 90, fill="#F1F3F5")
    synth.triangle(img, 460, 40, 150, 100, fill="#F1F3F5")
    synth.line(img, 100, 300, 700, 300, arrow=True)
    kinds = sorted(d.kind for d in detect(img))
    assert kinds == ["arrow", "ellipse", "rect", "triangle"]


def test_SHP_09_nested():
    img = synth.canvas()
    synth.rect(img, 50, 50, 400, 300, fill="#F1F3F5", stroke="#343A40", t=3)
    synth.ellipse(img, 150, 120, 150, 100, fill="#FFE3E3", stroke="#E03131", t=2)
    kinds = sorted(d.kind for d in detect(img))
    assert kinds == ["ellipse", "rect"]


def test_SHP_09b_nested_in_hollow():
    img = synth.canvas()
    synth.rect(img, 50, 50, 400, 300, fill=None, t=3)
    synth.rect(img, 150, 120, 100, 80, fill="#D3F9D8")
    assert sorted(d.kind for d in detect(img)) == ["rect", "rect"]


def test_SHP_10_empty_and_tiny():
    assert detect(synth.canvas()) == []
    assert detect(np.zeros((1, 1, 3), np.uint8)) == []
    assert detect(np.zeros((0, 0, 3), np.uint8)) == []


def test_SHP_11_noise_ignored():
    img = synth.canvas()
    rng = np.random.default_rng(1)
    for _ in range(40):
        x, y = rng.integers(0, 630), rng.integers(0, 390)
        img[y:y + 3, x:x + 3] = 0
    synth.rect(img, 100, 80, 200, 120, fill="#F1F3F5")
    assert [d.kind for d in detect(img)] == ["rect"]


def test_SHP_12_dark_background():
    img = synth.canvas(bg="#1E1E1E")
    synth.rect(img, 100, 80, 200, 120, fill="#2B8A3E", stroke="#FFFFFF")
    synth.ellipse(img, 350, 80, 150, 150, fill=None, stroke="#FFFFFF")
    assert sorted(d.kind for d in detect(img)) == ["ellipse", "rect"]


def test_SHP_13_jpeg_noise():
    img = synth.canvas()
    synth.rect(img, 60, 80, 200, 120, fill="#F1F3F5")
    synth.ellipse(img, 350, 80, 150, 150, fill="#D0EBFF")
    img = synth.jpeg(img, 50)
    assert sorted(d.kind for d in detect(img)) == ["ellipse", "rect"]


def test_SHP_14_text_mask_excludes_letters():
    img = synth.canvas()
    synth.rect(img, 100, 80, 260, 120, fill="#F1F3F5")
    tb_in = synth.text_blob(img, 150, 150, "HELLO")
    tb_out = synth.text_blob(img, 420, 300, "OUTSIDE")
    found = detect(img, text_boxes=[tb_in, tb_out])
    assert [d.kind for d in found] == ["rect"]


def test_SHP_15_gray_and_bgra_input():
    img = synth.canvas()
    synth.rect(img, 100, 80, 200, 120, fill="#ADB5BD", stroke="#000000")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    assert [d.kind for d in detect(gray)] == ["rect"]
    assert [d.kind for d in detect(bgra)] == ["rect"]


def _match(found, gts):
    used = set()
    tp = 0
    for g in gts:
        for i, d in enumerate(found):
            if i in used or d.kind != g.kind:
                continue
            if g.kind in ("line", "arrow"):
                ok = all(abs(a - b) <= 8 for p, q in zip(sorted(d.points), sorted(g.points)) for a, b in zip(p, q))
                if g.kind == "arrow":
                    ok = ok and abs(d.points[1][0] - g.points[1][0]) <= 8 and abs(d.points[1][1] - g.points[1][1]) <= 8
            else:
                ok = iou(box(d), (g.x, g.y, g.w, g.h)) >= 0.7
            if ok:
                used.add(i)
                tp += 1
                break
    return tp, len(found), len(gts)


@pytest.mark.slow
def test_SHP_16_synthetic_f1():
    tp = nf = ng = 0
    for seed in range(60):
        img, gts = synth.scene(seed)
        if seed % 3 == 0:
            img = synth.jpeg(img, 70)
        a, b, c = _match(detect(img), gts)
        tp, nf, ng = tp + a, nf + b, ng + c
    precision, recall = tp / max(nf, 1), tp / max(ng, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    assert f1 >= 0.95, (precision, recall, f1)


# --- post-processing for PowerPoint ------------------------------------------

def test_attach_text_to_containing_shape():
    shapes = [Detected("rect", 0, 0, 200, 100), Detected("rect", 50, 20, 80, 50)]
    lines = [("inner", (60, 30, 40, 20)), ("outer", (5, 80, 50, 15)), ("free", (500, 500, 30, 10))]
    rest = attach_text(shapes, lines)
    assert shapes[1].text == "inner"      # smallest shape that contains the text
    assert shapes[0].text == "outer"
    assert rest == [("free", (500, 500, 30, 10))]


def test_attach_multiple_lines_join():
    shapes = [Detected("rect", 0, 0, 200, 100)]
    attach_text(shapes, [("line2", (10, 50, 50, 15)), ("line1", (10, 10, 50, 15))])
    assert shapes[0].text == "line1\nline2"


def test_to_drawing_links_arrows_to_nearby_shapes():
    ds = [
        Detected("rect", 20, 40, 150, 64, fill="#F1F3F5", stroke="#343A40", text="요청 접수"),
        Detected("rect", 240, 40, 150, 64, fill="#F1F3F5", stroke="#343A40", text="검토"),
        Detected("arrow", 170, 72, 70, 0, stroke="#343A40", points=[(172, 72), (238, 72)]),
        Detected("line", 500, 300, 100, 0, stroke="#000000", points=[(500, 300), (600, 300)]),
    ]
    shapes, conns = to_drawing(ds)
    assert [s.text for s in shapes] == ["요청 접수", "검토"]
    assert (conns[0].start, conns[0].end, conns[0].arrow) == (0, 1, True)
    assert (conns[1].start, conns[1].end, conns[1].arrow) == (None, None, False)
    assert (conns[1].x1, conns[1].x2) == (500, 600)
