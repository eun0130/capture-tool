"""Monkey test: thousands of random clicks, drags, keys and buttons on the capture screen and the
edit window (fake screen / OCR / PowerPoint / AI). No error may surface anywhere — including
inside Qt slots, where an exception would otherwise only be printed."""
import random
import sys

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from capture_tool.core.ai_service import AiResult
from capture_tool.core.ocr import OcrLine
from tests.scrollsim import make_page
from tests.test_app import FakeOcr, FakePpt, drag, make  # noqa: F401 (fixture)

KEYS = [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Delete, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
        Qt.Key_BracketLeft, Qt.Key_BracketRight, Qt.Key_R, Qt.Key_O, Qt.Key_L, Qt.Key_A, Qt.Key_C, Qt.Key_P,
        Qt.Key_T, Qt.Key_N, Qt.Key_H, Qt.Key_M, Qt.Key_K, Qt.Key_V, Qt.Key_F3]
CTRL_KEYS = [Qt.Key_Z, Qt.Key_Y, Qt.Key_B, Qt.Key_I, Qt.Key_U, Qt.Key_5, Qt.Key_BracketLeft,
             Qt.Key_BracketRight]
SIDE = ["copy", "text", "ppt", "ppt_shapes", "pin", "link_file", "save"]
OCR_ACTIONS = ["all", "translate", "summarize", "window", "back"]


class FakeAi:
    busy = False

    def translate(self, text, src=None, tgt=None, cancel=None):
        return AiResult(text[:30], "local", "ko", "en")

    def summarize(self, text, lang="ko", on_text=None, cancel=None):
        return AiResult("• 요점", "local", tgt=lang)

    def preload(self, text):
        pass

    def unload(self):
        pass


@pytest.fixture
def errors(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: seen.append((t, v)))
    return seen


def setup(c):
    c.powerpoint = FakePpt()
    c.ai = FakeAi()
    c.uploader = lambda png, expiry: "https://litter.catbox.moe/m.png"
    c.ask_share_consent = lambda: True
    c.ask_save_path = lambda default, parent=None: None      # "cancel" in the save dialog


def random_point(rr, w, h):
    return QPoint(rr.randint(-20, w + 20), rr.randint(-20, h + 20))


def act(rr, c, step):
    if c.session.state.name == "IDLE":
        if c.editor is None and rr.random() < 0.15:
            c.open_editor(make_page(rr.randint(200, 3000), w=rr.randint(100, 900), seed=step), 96, "monkey")
        else:
            c.start_capture()
        return
    ov = c.active_overlay or (c.overlays[0] if c.overlays else None)
    if ov is None:
        c.cancel()
        return
    w, h = max(1, ov.width()), max(1, ov.height())
    r = rr.random()
    if r < 0.30:
        a, b = random_point(rr, w, h), random_point(rr, w, h)
        drag(ov, (a.x(), a.y()), (b.x(), b.y()))
    elif r < 0.40:
        QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, random_point(rr, w, h))
    elif r < 0.55:
        QTest.keyClick(ov, rr.choice(KEYS))
    elif r < 0.62:
        QTest.keyClick(ov, rr.choice(CTRL_KEYS), Qt.ControlModifier)
    elif r < 0.75 and c.session.state.name == "EDITING":
        if ov.ocr_lines is not None:
            c.on_ocr_action(rr.choice(OCR_ACTIONS))
        else:
            name = rr.choice(SIDE)
            if name in ov.side_bar.buttons or name in ("link_file", "save"):
                ov.side_bar.trigger(name)
    elif r < 0.85:
        ov.set_tool(rr.choice(["select", "rect", "ellipse", "line", "arrow", "curve", "pen", "text", "step",
                               "highlight", "mosaic", "lasso"]))
        ov.toolbar.set_color(rr.choice(["#E03131", "#FFE066", "#000000"]))
        if rr.random() < 0.3:
            ov.toolbar.choose_symbol(rr.choice("★✓①※"))
        if rr.random() < 0.3:
            ov.toolbar.set_bg(rr.choice([None, "#FFEC99"]))
    elif r < 0.9 and c.editor is not None:
        rr.choice([lambda: c.editor.zoom_by(1), lambda: c.editor.zoom_by(-1), c.editor.fit_width,
                   lambda: c.editor.set_zoom(rr.choice([0.1, 1.0, 4.0]))])()
    elif r < 0.95 and ov._editor is not None:
        ov._editor.insert(rr.choice(["가", "abc", "\n", "😀", ""]))
    else:
        c.cancel()
    if c.ai_window is not None and rr.random() < 0.3:
        c.ai_window.trigger(rr.choice(["copy", "ppt", "cancel", "close"]))
    if c.text_panel is not None and rr.random() < 0.3:
        rr.choice([c.text_panel.copy_all, c.text_panel.copy_table, c.text_panel.copy_selected, c.text_panel.close])()
    if c.pins and rr.random() < 0.5:
        c.close_pins()


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_MONKEY_01_random_use_never_errors(make, errors, seed):
    lines = [OcrLine("견적 요약", (10, 10, 120, 24), 0.95), OcrLine("010-1234-5678", (10, 50, 160, 24), 0.95),
             OcrLine("Quarterly revenue", (200, 10, 200, 24), 0.95)]
    c = make(ocr=FakeOcr(lines))
    setup(c)
    rr = random.Random(seed)
    for step in range(400):
        act(rr, c, step)
        assert not errors, (step, errors)
        if c.session.state.name == "EDITING":
            assert c.active_overlay is not None and c.session.document is not None
            sel = c.session.selection
            assert sel.w > 0 and sel.h > 0
    c.close_all()
    assert not errors
