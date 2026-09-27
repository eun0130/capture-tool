"""PowerPoint sending logic with a fake COM application (no PowerPoint needed).

Covers: what gets inserted (picture / text / native shapes), where (current slide, new deck),
size & placement, and the failure modes that used to hang the app (busy/frozen PowerPoint)."""
import threading
import time

import numpy as np
import pytest

from capture_tool.platform import powerpoint as pp
from capture_tool.platform.powerpoint import (ClipboardShapes, Picture, PowerPointTimeout, PowerPointUnavailable,
                                              TextItem, place, send)


class Shape:
    def __init__(self, kind, left, top, width, height, text=""):
        self.kind, self.Left, self.Top, self.Width, self.Height = kind, left, top, width, height
        self.TextFrame = type("TF", (), {})()
        self.TextFrame.TextRange = type("TR", (), {"Text": text})()
        self.TextFrame.TextRange.Font = type("F", (), {"Name": "", "NameFarEast": "", "Size": 18})()
        self.TextFrame.WordWrap = False
        self.TextFrame.AutoSize = 0


class Shapes:
    def __init__(self, slide):
        self.items, self.slide = [], slide

    @property
    def Count(self):
        return len(self.items)

    def AddPicture(self, path, link, save, left, top, width, height):
        self.slide.app.calls.append(("picture", path))
        import os
        assert os.path.isfile(path)
        s = Shape("picture", left, top, width, height)
        self.items.append(s)
        return s

    def AddTextbox(self, orientation, left, top, width, height):
        s = Shape("textbox", left, top, width, height)
        self.items.append(s)
        return s

    def Paste(self):
        self.slide.app.calls.append(("paste",))
        n = self.slide.app.paste_count
        self.items.extend(Shape("pasted", 0, 0, 10, 10) for _ in range(n))
        return type("Range", (), {"Count": n})()


class Slide:
    def __init__(self, app, index):
        self.app, self.SlideIndex = app, index
        self.Shapes = Shapes(self)


class Slides:
    def __init__(self, app):
        self.app, self.items = app, []

    @property
    def Count(self):
        return len(self.items)

    def Add(self, index, layout):
        s = Slide(self.app, index)
        self.items.insert(index - 1, s)
        return s

    def __call__(self, i):
        return self.items[i - 1]


class Pres:
    def __init__(self, app):
        self.Slides = Slides(app)
        self.PageSetup = type("PS", (), {"SlideWidth": 960.0, "SlideHeight": 540.0})()


class Presentations:
    def __init__(self, app):
        self.app, self.items = app, []

    @property
    def Count(self):
        return len(self.items)

    def Add(self, WithWindow=True):
        p = Pres(self.app)
        self.items.append(p)
        self.app.ActivePresentation = p
        return p


class FakeApp:
    def __init__(self, with_deck=False, current_slide=None, view_fails=False, paste_count=3):
        self.calls, self.paste_count = [], paste_count
        self.Visible = False
        self.Presentations = Presentations(self)
        self.ActivePresentation = None
        self.view_fails = view_fails
        if with_deck:
            p = self.Presentations.Add()
            for i in range(3):
                p.Slides.Add(i + 1, 12)
            self._current = p.Slides(current_slide or 2)

    @property
    def ActiveWindow(self):
        app = self

        class View:
            @property
            def Slide(self):
                if app.view_fails:
                    raise RuntimeError("slide sorter / slide show has no current slide")
                return app._current
        return type("W", (), {"View": View()})()


IMG = np.full((180, 300, 3), 200, np.uint8)


def test_PPT_01_picture_goes_into_the_slide_being_viewed_at_screen_size():
    app = FakeApp(with_deck=True, current_slide=2)
    r = send(Picture(IMG, dpi=144), app_factory=lambda: app)
    slide2 = app.ActivePresentation.Slides(2)
    assert r.added == 1 and slide2.Shapes.Count == 1
    pic = slide2.Shapes.items[0]
    assert (pic.Width, pic.Height) == (150, 90)                    # 300 px at 144 dpi
    assert (pic.Left, pic.Top) == ((960 - 150) / 2, (540 - 90) / 2)  # centered


def test_PPT_02_no_deck_open_creates_one_with_a_blank_slide():
    app = FakeApp()
    r = send(Picture(IMG), app_factory=lambda: app)
    assert app.Presentations.Count == 1 and app.ActivePresentation.Slides.Count == 1
    assert r.added == 1 and app.Visible


def test_PPT_03_no_current_slide_in_view_uses_last_slide():
    app = FakeApp(with_deck=True, view_fails=True)
    send(Picture(IMG), app_factory=lambda: app)
    assert app.ActivePresentation.Slides(3).Shapes.Count == 1


def test_PPT_04_text_becomes_an_editable_text_box():
    app = FakeApp(with_deck=True)
    r = send(TextItem("견적 요약\n담당 홍길동", font_family="Malgun Gothic", font_size=18), app_factory=lambda: app)
    tb = app.ActivePresentation.Slides(2).Shapes.items[0]
    assert r.added == 1 and tb.kind == "textbox"
    assert tb.TextFrame.TextRange.Text == "견적 요약\r담당 홍길동"   # PowerPoint paragraphs use \r
    assert tb.TextFrame.TextRange.Font.Name == "Malgun Gothic"
    assert tb.TextFrame.TextRange.Font.NameFarEast == "Malgun Gothic"


def test_PPT_05_native_shapes_use_object_model_paste_not_ui_commands():
    app = FakeApp(with_deck=True, paste_count=3)
    r = send(ClipboardShapes(), app_factory=lambda: app)
    assert r.added == 3 and ("paste",) in app.calls


def test_PPT_06_picture_larger_than_slide_is_scaled_to_fit():
    left, top, w, h = place(3000, 1500, 960, 540)
    assert w <= 960 * 0.9 + 0.5 and h <= 540 * 0.9 + 0.5
    assert abs(w / h - 2.0) < 0.01                                  # keeps its shape
    assert left >= 0 and top >= 0


def test_PPT_07_tiny_and_zero_sizes_are_safe():
    assert place(0, 0, 960, 540)[2] > 0
    left, top, w, h = place(10, 10, 960, 540)
    assert (w, h) == (10, 10)


def test_PPT_08_frozen_powerpoint_times_out_instead_of_hanging():
    def frozen():
        time.sleep(30)
    t = time.perf_counter()
    with pytest.raises(PowerPointTimeout):
        send(Picture(IMG), app_factory=frozen, timeout=0.5)
    assert time.perf_counter() - t < 2.0


def test_PPT_09_com_errors_become_unavailable():
    class Broken(FakeApp):
        @property
        def Presentations(self):
            raise RuntimeError("RPC_E_CALL_REJECTED (0x80010001)")

        @Presentations.setter
        def Presentations(self, v):
            pass
    with pytest.raises(PowerPointUnavailable):
        send(Picture(IMG), app_factory=Broken)


def test_PPT_10_not_installed(monkeypatch):
    monkeypatch.setattr(pp, "installed", lambda: False)
    with pytest.raises(PowerPointUnavailable) as e:
        send(Picture(IMG))
    assert "설치" in str(e.value)


def test_PPT_11_nothing_pasted_is_reported():
    app = FakeApp(with_deck=True, paste_count=0)
    assert send(ClipboardShapes(), app_factory=lambda: app).added == 0


def test_PPT_12_temp_picture_file_is_removed():
    app = FakeApp(with_deck=True)
    send(Picture(IMG), app_factory=lambda: app)
    import os
    path = next(c[1] for c in app.calls if c[0] == "picture")
    assert not os.path.exists(path)


def test_PPT_13_sender_allows_one_job_at_a_time():
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return FakeApp(with_deck=True)
    sender = pp.PowerPointSender(app_factory=slow, timeout=5)
    th = threading.Thread(target=lambda: sender.send(Picture(IMG)))
    th.start()
    started.wait(2)
    assert sender.busy
    with pytest.raises(pp.PowerPointBusy):
        sender.send(Picture(IMG))
    release.set()
    th.join(5)
    assert not sender.busy


def test_PPT_14_huge_text_is_cut_so_powerpoint_cannot_freeze():
    from capture_tool.platform.powerpoint import MAX_TEXT_CHARS
    app = FakeApp(with_deck=True)
    big = "\n".join("\t".join(["셀"] * 300) for _ in range(250))     # 233×316-like table text
    send(TextItem(big), app_factory=lambda: app)
    tb = app.ActivePresentation.Slides(2).Shapes.items[0]
    assert len(tb.TextFrame.TextRange.Text) <= MAX_TEXT_CHARS + 1
    assert tb.Width > 0 and tb.Height > 0


def test_PPT_15_clip_text_keeps_whole_lines_and_reports_cut():
    from capture_tool.platform.powerpoint import MAX_TEXT_CHARS, clip_text
    assert clip_text("짧은 글") == ("짧은 글", False)
    text, cut = clip_text("\n".join(["가" * 100] * 200))
    assert cut and len(text) <= MAX_TEXT_CHARS + 1 and text.endswith("…")
    assert all(l in ("가" * 100, "…") for l in text.split("\n"))
