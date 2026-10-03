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
    name: str = ""


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


def side_bar_position(sel: Rect, monitor: Rect, w: int, h: int, gap: int = 8) -> tuple[int, int]:
    """Vertical quick-action bar: right of the selection, else left, else inside its right edge."""
    if sel.right + gap + w <= monitor.right:
        x = sel.right + gap
    elif sel.x - gap - w >= monitor.x:
        x = sel.x - gap - w
    else:
        x = min(sel.right, monitor.right) - w - gap
    y = max(monitor.y, min(sel.y, monitor.bottom - h - gap))
    return x, y


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def layout_bars(sel: Rect, monitor: Rect, tb_size: tuple[int, int], sb_size: tuple[int, int],
                gap: int = 8) -> tuple[tuple[int, int], tuple[int, int]]:
    """Place the drawing toolbar and the quick-action side bar around the selection
    so they never cover each other and stay on the monitor."""
    tw, th = tb_size
    sw, sh = sb_size
    sx, sy = side_bar_position(sel, monitor, sw, sh, gap)
    sb = Rect(sx, sy, sw, sh)
    tx, ty = toolbar_position(sel, monitor, tw, th, gap)
    if not _overlaps(Rect(tx, ty, tw, th), sb):
        return (tx, ty), (sx, sy)
    lo, hi = monitor.x + gap, monitor.right - tw - gap
    # 1) slide the toolbar sideways, away from the side bar
    for x in (sb.x - gap - tw, sb.right + gap):
        if lo <= x <= hi and not _overlaps(Rect(x, ty, tw, th), sb):
            return (x, ty), (sx, sy)
    # 2) drop the toolbar below the side bar, or lift it above
    x = min(max(sel.x, lo), hi)
    for y in (max(sel.bottom, sb.bottom) + gap, min(sel.y, sb.y) - gap - th):
        if monitor.y <= y <= monitor.bottom - th and not _overlaps(Rect(x, y, tw, th), sb):
            return (x, y), (sx, sy)
    # 3) crowded screen: move the side bar up/down beside the toolbar row
    tb = Rect(tx, ty, tw, th)
    for y in (tb.y - gap - sh, tb.bottom + gap):
        if monitor.y <= y <= monitor.bottom - sh and not _overlaps(Rect(sx, y, sw, sh), tb):
            return (tx, ty), (sx, y)
    # 4) last resort: side bar at the screen corner away from the toolbar
    corner_x = monitor.x + gap if tb.x > monitor.x + sw + 2 * gap else monitor.right - sw - gap
    return (tx, ty), (corner_x, monitor.y + gap)


def layout_action_bars(sel: Rect, monitor: Rect, tb_size: tuple[int, int], ab_size: tuple[int, int],
                       gap: int = 8) -> tuple[tuple[int, int], tuple[int, int]]:
    """The action bar (one row) right under the selection, the drawing toolbar under it; when
    there is no room below: above, then inside the selection's bottom. Both stay on the monitor
    and never cover each other. Returns ((toolbar x, y), (action bar x, y))."""
    tw, th = tb_size
    aw, ah = ab_size

    def cx(w):
        return max(monitor.x, min(sel.x, monitor.right - w))

    tx, ax = cx(tw), cx(aw)
    below, above = sel.bottom + gap, sel.y - gap
    inside_ab = min(sel.bottom, monitor.bottom) - gap - ah
    options = [
        (below + ah + gap, below),                      # bar below, toolbar below the bar
        (above - th, below),                            # bar below, toolbar above
        (below, above - ah),                            # bar above, toolbar below
        (above - ah - gap - th, above - ah),            # both above
        (inside_ab - gap - th, inside_ab),              # both inside the bottom of the selection
        (monitor.y + gap, monitor.bottom - ah - gap),   # last resort: toolbar top, bar bottom
    ]
    for ty, ay in options:
        t, a = Rect(tx, ty, tw, th), Rect(ax, ay, aw, ah)
        if (monitor.y <= ty and t.bottom <= monitor.bottom and monitor.y <= ay and a.bottom <= monitor.bottom
                and not _overlaps(t, a)):
            return (tx, ty), (ax, ay)
    ty, ay = monitor.y, max(monitor.y, monitor.bottom - ah)
    if _overlaps(Rect(tx, ty, tw, th), Rect(ax, ay, aw, ah)):       # tiny monitor: side by side
        ax = max(monitor.x, min(tx + tw + gap, monitor.right - aw))
    return (tx, ty), (ax, ay)


def match_screen(monitor: Monitor, screens: Sequence[tuple[str, tuple[int, int, int, int], float]]) -> str | None:
    """Pick the Qt screen (name, (x, y, w, h) logical geometry, dpr) that shows `monitor`.

    Qt on Windows keeps each screen's physical top-left as its geometry origin while the
    size is divided by its dpr; names are marketing names, not GDI device names."""
    if not screens:
        return None
    r = monitor.rect
    for name, _, _ in screens:
        if name == monitor.name:
            return name

    def score(s):
        _, (x, y, w, h), dpr = s
        origin = abs(x - r.x) + abs(y - r.y)
        size = abs(w * dpr - r.w) + abs(h * dpr - r.h)
        return origin * 4 + size + abs(dpr - monitor.scale) * 1000

    return min(screens, key=score)[0]


def to_logical(r: Rect, scale: float) -> Rect:
    return Rect(round(r.x / scale), round(r.y / scale), round(r.w / scale), round(r.h / scale))


def to_physical(r: Rect, scale: float) -> Rect:
    return Rect(round(r.x * scale), round(r.y * scale), round(r.w * scale), round(r.h * scale))
