"""User-drawn annotations -> native PowerPoint shapes (exact, no recognition needed)."""
from __future__ import annotations

from .annotations import Shape
from .drawingml import DConnector, DShape

STEP_SIZE = 28


def annotations_to_drawing(anns: list[Shape], offset=(0, 0)) -> tuple[list[DShape], list[DConnector]]:
    ox, oy = offset
    shapes: list[DShape] = []
    conns: list[DConnector] = []
    for a in anns:
        if a.kind in ("rect", "ellipse"):
            (x1, y1), (x2, y2) = a.points
            x, y = min(x1, x2), min(y1, y2)
            shapes.append(DShape("rect" if a.kind == "rect" else "ellipse", x + ox, y + oy,
                                 abs(x2 - x1), abs(y2 - y1), fill=a.color if a.fill else None,
                                 stroke=a.color, stroke_width=a.width))
        elif a.kind in ("line", "arrow"):
            (x1, y1), (x2, y2) = a.points
            conns.append(DConnector(x1=x1 + ox, y1=y1 + oy, x2=x2 + ox, y2=y2 + oy, color=a.color,
                                    width=a.width, arrow=a.kind == "arrow"))
        elif a.kind == "text" and a.text:
            (x, y), = a.points
            lines = a.text.split("\n")
            w = max(len(l) for l in lines) * 16 + 16
            h = len(lines) * 24 + 8
            shapes.append(DShape("rect", x + ox, y + oy, w, h, fill=None, stroke=None, text=a.text,
                                 text_color=a.color, font_size=14))
        elif a.kind == "step" and a.number is not None:
            (cx, cy), = a.points
            r = STEP_SIZE / 2
            shapes.append(DShape("ellipse", cx - r + ox, cy - r + oy, STEP_SIZE, STEP_SIZE, fill=a.color,
                                 stroke=None, text=str(a.number), text_color="#FFFFFF", font_size=11, bold=True))
    return shapes, conns
