"""Rectangles, monitors and placement math. Coordinates are physical pixels in the
Windows virtual-screen space, so secondary monitors may have negative x/y."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

Point = tuple[float, float]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_points(cls, p1: Point, p2: Point) -> Rect:
        x1, y1 = round(p1[0]), round(p1[1])
        x2, y2 = round(p2[0]), round(p2[1])
        return cls(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, p: Point) -> bool:
        """Half-open: the right/bottom edge belongs to the next rectangle."""
        return self.x <= p[0] < self.right and self.y <= p[1] < self.bottom

    def distance_to(self, p: Point) -> float:
        dx = max(self.x - p[0], 0, p[0] - (self.right - 1))
        dy = max(self.y - p[1], 0, p[1] - (self.bottom - 1))
        return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True)
class Monitor:
    id: int
    rect: Rect
    scale: float = 1.0
    primary: bool = False


def monitor_at(p: Point, monitors: Sequence[Monitor]) -> Monitor:
    if not monitors:
        raise ValueError("no monitors")
    for m in monitors:
        if m.rect.contains(p):
            return m
    return min(monitors, key=lambda m: m.rect.distance_to(p))


def order_cursor_first(monitors: Sequence[Monitor], p: Point) -> list[Monitor]:
    first = monitor_at(p, monitors)
    return [first] + [m for m in monitors if m is not first]


def union(rects: Iterable[Rect]) -> Rect:
    rects = list(rects)
    if not rects:
        raise ValueError("no rects")
    x = min(r.x for r in rects)
    y = min(r.y for r in rects)
    return Rect(x, y, max(r.right for r in rects) - x, max(r.bottom for r in rects) - y)


def virtual_bounds(monitors: Sequence[Monitor]) -> Rect:
    return union(m.rect for m in monitors)


def clamp_rect(r: Rect, bounds: Rect) -> Rect | None:
    x1, y1 = max(r.x, bounds.x), max(r.y, bounds.y)
    x2, y2 = min(r.right, bounds.right), min(r.bottom, bounds.bottom)
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x1, y1, x2 - x1, y2 - y1)


def selection_from_drag(p1: Point, p2: Point, bounds: Rect, min_size: int = 3) -> Rect | None:
    r = clamp_rect(Rect.from_points(p1, p2), bounds) if p1 != p2 else None
    if r is None or r.w < min_size or r.h < min_size:
        return None
    return r


def nudge(r: Rect, dx: int, dy: int, bounds: Rect) -> Rect:
    x = min(max(r.x + dx, bounds.x), bounds.right - r.w)
    y = min(max(r.y + dy, bounds.y), bounds.bottom - r.h)
    return Rect(x, y, r.w, r.h)


def toolbar_position(sel: Rect, monitor: Rect, tb_w: int, tb_h: int, gap: int = 8) -> tuple[int, int]:
    """Below the selection if it fits, else above, else inside its bottom edge."""
    if sel.bottom + gap + tb_h <= monitor.bottom:
        y = sel.bottom + gap
    elif sel.y - gap - tb_h >= monitor.y:
        y = sel.y - gap - tb_h
    else:
        y = min(sel.bottom, monitor.bottom) - tb_h - gap
    x = min(max(sel.x, monitor.x + gap), monitor.right - tb_w - gap)
    return x, y


def to_logical(r: Rect, scale: float) -> Rect:
    return Rect(round(r.x / scale), round(r.y / scale), round(r.w / scale), round(r.h / scale))


def to_physical(r: Rect, scale: float) -> Rect:
    return Rect(round(r.x * scale), round(r.y * scale), round(r.w * scale), round(r.h * scale))
