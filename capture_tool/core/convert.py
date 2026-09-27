"""User-drawn annotations -> native PowerPoint shapes (exact, no recognition needed)."""
from __future__ import annotations

from .annotations import STEP_RADIUS, Shape
from .drawingml import DConnector, DShape


def annotations_to_drawing(anns: list[Shape], offset=(0, 0), scale: float = 1.0) -> tuple[list[DShape], list[DConnector]]:
    """Coordinates are physical px; `scale` (Windows display scale) turns font sizes into points."""
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
            bx1, by1, bx2, by2 = a.bbox()
            pt = round(a.font_size / scale * 0.75)  # px on screen -> points
            shapes.append(DShape("rect", bx1 + ox, by1 + oy, max(8, bx2 - bx1), max(8, by2 - by1),
                                 fill=None, stroke=None, text=a.text, text_color=a.color, font_size=pt,
                                 bold=a.bold, italic=a.italic, underline=a.underline, strike=a.strike))
        elif a.kind == "step" and a.number is not None:
            (cx, cy), = a.points
            d = STEP_RADIUS * 2
            shapes.append(DShape("ellipse", cx - STEP_RADIUS + ox, cy - STEP_RADIUS + oy, d, d, fill=a.color,
                                 stroke=None, text=str(a.number), text_color="#FFFFFF",
                                 font_size=round(15 / scale * 0.75), bold=True))
    return shapes, conns
