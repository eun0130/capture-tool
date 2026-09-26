"""Capture session state machine: IDLE -> SELECTING -> EDITING -> (finish) -> IDLE."""
from __future__ import annotations

from enum import Enum

from .annotations import Document
from .geometry import Rect, selection_from_drag


class State(Enum):
    IDLE = "idle"
    SELECTING = "selecting"
    EDITING = "editing"


class Action(Enum):
    NONE = "none"
    CANCEL = "cancel"
    COPY = "copy"
    SAVE = "save"
    SAVE_AS = "save_as"
    PIN = "pin"


class CaptureSession:
    def __init__(self):
        self.state = State.IDLE
        self.bounds: Rect | None = None
        self.selection: Rect | None = None
        self.document: Document | None = None
        self.result: Rect | None = None
        self.result_document: Document | None = None

    def hotkey(self, bounds: Rect) -> bool:
        """Start a capture. Ignored (False) while one is already running."""
        if self.state is not State.IDLE:
            return False
        self.bounds = bounds
        self.selection = None
        self.document = None
        self.state = State.SELECTING
        return True

    def drag(self, p1, p2) -> None:
        if self.state is not State.SELECTING:
            return
        r = selection_from_drag(p1, p2, self.bounds)
        if r is None:
            return
        self._select(r)

    def select(self, r: Rect) -> None:
        """Pick a region directly (e.g. auto-detected window)."""
        if self.state is State.SELECTING:
            self._select(r)

    def _select(self, r: Rect) -> None:
        self.selection = r
        self.document = Document(r.w, r.h)
        self.state = State.EDITING

    def resize(self, r: Rect) -> None:
        if self.state is not State.EDITING or r.w < 1 or r.h < 1:
            return
        old = self.selection
        self.document.rebase(old.x - r.x, old.y - r.y, r.w, r.h)
        self.selection = r

    def key(self, key: str, ctrl: bool = False, shift: bool = False) -> Action:
        k = key.lower()
        if k == "escape":
            self._reset()
            return Action.CANCEL
        if self.state is not State.EDITING:
            return Action.NONE
        action = Action.NONE
        if k == "enter" or (ctrl and k == "c"):
            action = Action.COPY
        elif ctrl and k == "s":
            action = Action.SAVE_AS if shift else Action.SAVE
        elif k == "f3":
            action = Action.PIN
        if action is not Action.NONE:
            self.result = self.selection
            self.result_document = self.document
            self._reset()
        return action

    def _reset(self) -> None:
        self.state = State.IDLE
        self.selection = None
        self.document = None
