"""Synthetic diagram generator with ground truth, for shape-recognition tests."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import cv2
import numpy as np

AA = cv2.LINE_AA


def bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


@dataclass
class GT:
    kind: str
    x: int
    y: int
    w: int
    h: int
    fill: str | None = None
    stroke: str | None = None
    points: list = field(default_factory=list)


def canvas(w=640, h=400, bg="#FFFFFF"):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = bgr(bg)
    return img


def rect(img, x, y, w, h, fill=None, stroke="#343A40", t=2, radius=0):
    kind = "roundRect" if radius else "rect"
    mask = np.zeros(img.shape[:2], np.uint8)
    if radius:
        r = radius
        cv2.rectangle(mask, (x + r, y), (x + w - r, y + h), 255, -1)
        cv2.rectangle(mask, (x, y + r), (x + w, y + h - r), 255, -1)
        for cx, cy in [(x + r, y + r), (x + w - r, y + r), (x + r, y + h - r), (x + w - r, y + h - r)]:
            cv2.circle(mask, (cx, cy), r, 255, -1, AA)
    else:
        cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    _paint(img, mask, fill, stroke, t)
    return GT(kind, x, y, w, h, fill, stroke)


def ellipse(img, x, y, w, h, fill=None, stroke="#343A40", t=2):
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(mask, (x + w // 2, y + h // 2), (w // 2, h // 2), 0, 0, 360, 255, -1, AA)
    _paint(img, mask, fill, stroke, t)
    return GT("ellipse", x, y, w, h, fill, stroke)


def triangle(img, x, y, w, h, fill=None, stroke="#343A40", t=2):
    mask = np.zeros(img.shape[:2], np.uint8)
    pts = np.array([[x + w // 2, y], [x, y + h], [x + w, y + h]], np.int32)
    cv2.fillPoly(mask, [pts], 255, AA)
    _paint(img, mask, fill, stroke, t)
    return GT("triangle", x, y, w, h, fill, stroke)


def _paint(img, mask, fill, stroke, t):
    """Fill the shape, then draw a stroke band of thickness t just inside its edge."""
    soft = mask.astype(np.float32) / 255.0
    if fill:
        _blend(img, soft, fill)
    if stroke:
        k = np.ones((2 * t + 1, 2 * t + 1), np.uint8)
        inner = cv2.erode(mask, k)
        band = cv2.subtract(mask, inner).astype(np.float32) / 255.0
        _blend(img, band, stroke)


def _blend(img, alpha, color):
    c = np.array(bgr(color), np.float32)
    a = alpha[..., None]
    img[:] = (img.astype(np.float32) * (1 - a) + c * a).round().astype(np.uint8)


def line(img, x1, y1, x2, y2, color="#343A40", t=2, arrow=False):
    tip = (x2, y2)
    if arrow:
        v = np.array([x2 - x1, y2 - y1], np.float64)
        n = np.linalg.norm(v)
        u = v / n
        size = 6 + 3 * t
        base = np.array([x2, y2]) - u * size
        perp = np.array([-u[1], u[0]]) * size * 0.6
        pts = np.array([tip, base + perp, base - perp], np.int32)
        cv2.fillPoly(img, [pts], bgr(color), AA)
        end = tuple(int(v) for v in base)
    else:
        end = tip
    cv2.line(img, (x1, y1), end, bgr(color), t, AA)
    xs, ys = sorted([x1, x2]), sorted([y1, y2])
    return GT("arrow" if arrow else "line", xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0],
              None, color, [(x1, y1), (x2, y2)])


def text_blob(img, x, y, text="ABC 가나", color="#1F2328", scale=0.7):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, bgr(color), 2, AA)
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    return (x - 2, y - h - 2, w + 4, h + base + 4)


PALETTE = ["#F1F3F5", "#FFE3E3", "#D0EBFF", "#D3F9D8", "#FFF3BF", "#E5DBFF"]
STROKES = ["#343A40", "#E03131", "#1971C2", "#2F9E44", "#000000"]


def scene(seed: int, w=800, h=500):
    """3-6 non-overlapping shapes with ground truth."""
    rnd = random.Random(seed)
    img = canvas(w, h)
    gts: list[GT] = []
    taken: list[tuple[int, int, int, int]] = []
    kinds = ["rect", "roundRect", "ellipse", "triangle", "line", "arrow"]
    for _ in range(rnd.randint(3, 6)):
        for _try in range(30):
            k = rnd.choice(kinds)
            bw, bh = rnd.randint(70, 200), rnd.randint(50, 130)
            x, y = rnd.randint(10, w - bw - 10), rnd.randint(10, h - bh - 10)
            box = (x - 15, y - 15, x + bw + 15, y + bh + 15)
            if any(not (box[2] < t[0] or box[0] > t[2] or box[3] < t[1] or box[1] > t[3]) for t in taken):
                continue
            taken.append(box)
            fill = rnd.choice(PALETTE + [None])
            stroke = rnd.choice(STROKES)
            t = rnd.choice([2, 3])
            if k == "rect":
                gts.append(rect(img, x, y, bw, bh, fill, stroke, t))
            elif k == "roundRect":
                gts.append(rect(img, x, y, bw, bh, fill, stroke, t, radius=rnd.randint(10, min(bw, bh) // 3)))
            elif k == "ellipse":
                gts.append(ellipse(img, x, y, bw, bh, fill, stroke, t))
            elif k == "triangle":
                gts.append(triangle(img, x, y, bw, bh, fill, stroke, t))
            else:
                if rnd.random() < 0.5:
                    x1, y1, x2, y2 = x, y + bh // 2, x + bw, y + bh // 2
                else:
                    x1, y1, x2, y2 = x, y, x + bw, y + bh
                if rnd.random() < 0.5:
                    x1, y1, x2, y2 = x2, y2, x1, y1
                gts.append(line(img, x1, y1, x2, y2, stroke, t, arrow=(k == "arrow")))
            break
    return img, gts


def jpeg(img, q=60):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)
