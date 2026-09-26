"""Vector annotations drawn over a capture, with undo/redo history.
Coordinates are relative to the captured region (0..width, 0..height)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .color import normalize_hex

BOX_KINDS = {"rect", "ellipse", "highlight", "mosaic"}
LINE_KINDS = {"line", "arrow"}
PATH_KINDS = {"curve", "pen"}
POINT_KINDS = {"text", "step"}
KINDS = BOX_KINDS | LINE_KINDS | PATH_KINDS | POINT_KINDS
HISTORY_LIMIT = 100
MIN_BOX = 2
MIN_LINE = 3


@dataclass
class Shape:
    kind: str
    points: list = field(default_factory=list)
    color: str = "#E03131"
    width: float = 4
    fill: bool = False
    opacity: float = 1.0
    text: str | None = None
    number: int | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown shape kind: {self.kind!r}")
        self.color = normalize_hex(self.color)
        if not isinstance(self.width, (int, float)) or self.width <= 0:
            raise ValueError(f"width must be > 0: {self.width!r}")
        self.opacity = min(1.0, max(0.1, float(self.opacity)))
        self.points = [(p[0], p[1]) for p in self.points]

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)


def _valid(s: Shape) -> bool:
    if not s.points:
        return False
    if s.kind in BOX_KINDS:
        if len(s.points) != 2:
            return False
        (x1, y1), (x2, y2) = s.points
        return abs(x2 - x1) >= MIN_BOX and abs(y2 - y1) >= MIN_BOX
    if s.kind in LINE_KINDS:
        if len(s.points) != 2:
            return False
        (x1, y1), (x2, y2) = s.points
        return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 >= MIN_LINE
    if s.kind in PATH_KINDS:
        if len(s.points) < 2:
            return False
        x1, y1, x2, y2 = s.bbox()
        return max(x2 - x1, y2 - y1) >= MIN_LINE
    if s.kind == "text":
        return len(s.points) == 1 and bool(s.text and s.text.strip())
    if s.kind == "step":
        return len(s.points) == 1 and s.number is not None
    return False


class Document:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.shapes: list[Shape] = []
        self._undo: list[list[Shape]] = []
        self._redo: list[list[Shape]] = []

    # --- history -------------------------------------------------------
    def _commit(self, new_shapes: list[Shape]) -> None:
        self._undo.append(self.shapes)
        if len(self._undo) > HISTORY_LIMIT:
            self._undo.pop(0)
        self._redo.clear()
        self.shapes = new_shapes

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.shapes)
        self.shapes = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.shapes)
        self.shapes = self._redo.pop()
        return True

    # --- edits ---------------------------------------------------------
    def _clamp(self, p):
        return (min(max(p[0], 0), self.width), min(max(p[1], 0), self.height))

    def add(self, shape: Shape) -> bool:
        s = replace(shape, points=[self._clamp(p) for p in shape.points])
        if not _valid(s):
            return False
        self._commit(self.shapes + [s])
        return True

    def next_step_number(self) -> int:
        nums = [s.number for s in self.shapes if s.kind == "step" and s.number is not None]
        return max(nums, default=0) + 1

    def add_step(self, point, color: str) -> Shape:
        s = Shape(kind="step", points=[point], color=color, number=self.next_step_number())
        self.add(s)
        return self.shapes[-1]

    def _check(self, index: int) -> None:
        if not 0 <= index < len(self.shapes):
            raise IndexError(index)

    def delete(self, index: int) -> None:
        self._check(index)
        self._commit(self.shapes[:index] + self.shapes[index + 1:])

    def move(self, index: int, dx: float, dy: float) -> None:
        self._check(index)
        s = self.shapes[index]
        x1, y1, x2, y2 = s.bbox()
        dx = min(max(dx, -x1), self.width - x2)
        dy = min(max(dy, -y1), self.height - y2)
        moved = replace(s, points=[(p[0] + dx, p[1] + dy) for p in s.points])
        self._commit(self.shapes[:index] + [moved] + self.shapes[index + 1:])

    def rebase(self, dx: float, dy: float, width: int, height: int) -> None:
        """Region moved/resized: keep shapes at the same screen position (not undoable)."""
        self.width, self.height = width, height
        self.shapes = [replace(s, points=[self._clamp((p[0] + dx, p[1] + dy)) for p in s.points]) for s in self.shapes]
