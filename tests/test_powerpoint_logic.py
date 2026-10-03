"""PowerPoint sending logic with a fake COM application (no PowerPoint needed).

Covers: what gets inserted (picture / text / native shapes), where (current slide, new deck),
size & placement, and the failure modes that used to hang the app (busy/frozen PowerPoint)."""
import threading
import time

import numpy as np
import pytest

from capture_tool.platform import powerpoint as pp
from capture_tool.platform.powerpoint import (ClipboardShapes, Picture, PowerPointTimeout, PowerPointUnavailable,
                                              TableItem, TextItem, place, send)


class Shape:
    def __init__(self, kind, left, top, width, height, text=""):
        self.kind, self.Left, self.Top, self.Width, self.Height = kind, left, top, width, height
        self.TextFrame = type("TF", (), {})()
        self.TextFrame.TextRange = type("TR", (), {"Text": text})()
        self.TextFrame.TextRange.Font = type("F", (), {"Name": "", "NameFarEast": "", "Size": 18})()
        self.TextFrame.WordWrap = False
        self.TextFrame.AutoSize = 0
        self.selected = False

    def Select(self, replace=True):
        self.selected = True


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

    def AddTable(self, rows, cols, left, top, width, height):
        s = Shape("table", left, top, width, height)
        s.Table = FakeTable(rows, cols, self.slide.app.calls)
        s.HasTable = True
        self.items.append(s)
        return s

    def Paste(self):
        self.slide.app.calls.append(("paste",))
        n = self.slide.app.paste_count
        new = [Shape("pasted", 0, 0, 10, 10) for _ in range(n)]
        self.items.extend(new)
        rng = type("Range", (), {"Count": n})()
        rng.Select = lambda *a: [setattr(x, "selected", True) for x in new]
        return rng


class FakeTable:
    def __init__(self, rows, cols, calls=None):
        self.calls = calls if calls is not None else []
        self.Rows = type("Rows", (), {"Count": rows})()
        self.Columns = type("Cols", (), {"Count": cols})()
        self.cells = {(r, c): Shape("cell", 0, 0, 0, 0) for r in range(1, rows + 1) for c in range(1, cols + 1)}

    def Cell(self, r, c):
        cell = type("Cell", (), {})()
        cell.Shape = self.cells[(r, c)]
        cell.pos = (r, c)
        cell.Merge = lambda other: self.calls.append(("merge", (r, c), other.pos))
        return cell


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
        self.goto, self.goto_fails = [], False
        self.HWND = 4242
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

            def GotoSlide(self, index):
                if app.goto_fails:
                    raise RuntimeError("no window")
                app.goto.append(index)
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


# --- v0.3.5: put each capture on a NEW slide right after the one being viewed ----------------

def test_PPT_16_new_slide_after_the_current_one_and_shown():
    app = FakeApp(with_deck=True, current_slide=2)
    before = list(app.ActivePresentation.Slides.items)
    r = send(Picture(IMG), app_factory=lambda: app, new_slide=True)
    slides = app.ActivePresentation.Slides
    assert r.added == 1 and slides.Count == 4
    new = slides(3)
    assert new not in before and new.Shapes.Count == 1
    assert all(s.Shapes.Count == 0 for s in before)            # existing slides untouched
    assert app.goto == [3]                                     # PowerPoint shows the new slide


def test_PPT_17_no_deck_uses_the_new_deck_first_slide_only():
    app = FakeApp()
    send(Picture(IMG), app_factory=lambda: app, new_slide=True)
    assert app.ActivePresentation.Slides.Count == 1
    assert app.ActivePresentation.Slides(1).Shapes.Count == 1


def test_PPT_18_unknown_current_slide_appends_at_the_end():
    app = FakeApp(with_deck=True, view_fails=True)
    send(TextItem("가"), app_factory=lambda: app, new_slide=True)
    slides = app.ActivePresentation.Slides
    assert slides.Count == 4 and slides(4).Shapes.Count == 1


def test_PPT_19_new_slide_off_keeps_current_slide_behavior():
    app = FakeApp(with_deck=True, current_slide=2)
    send(Picture(IMG), app_factory=lambda: app, new_slide=False)
    assert app.ActivePresentation.Slides.Count == 3
    assert app.ActivePresentation.Slides(2).Shapes.Count == 1


def test_PPT_20_deck_without_slides_gets_one():
    app = FakeApp()
    app.Presentations.Add()
    send(ClipboardShapes(), app_factory=lambda: app, new_slide=True)
    assert app.ActivePresentation.Slides.Count == 1


def test_PPT_21_goto_failure_is_harmless():
    app = FakeApp(with_deck=True, current_slide=1)
    app.goto_fails = True
    r = send(Picture(IMG), app_factory=lambda: app, new_slide=True)
    assert r.added == 1 and app.ActivePresentation.Slides(2).Shapes.Count == 1


def test_PPT_22_sender_uses_its_new_slide_setting():
    app = FakeApp(with_deck=True, current_slide=2)
    sender = pp.PowerPointSender(app_factory=lambda: app, timeout=5)
    assert sender.new_slide is True                            # default: new slide
    sender.send(Picture(IMG))
    assert app.ActivePresentation.Slides.Count == 4
    sender.new_slide = False
    sender.send(Picture(IMG))
    assert app.ActivePresentation.Slides.Count == 4



# --- v0.6.1: PowerPoint comes to the front with the new object selected ------------------------------
def test_PPT_23_result_carries_the_powerpoint_window_and_selects_what_was_added():
    for item in (Picture(IMG), TextItem("가"), ClipboardShapes()):
        app = FakeApp(with_deck=True, current_slide=2)
        r = send(item, app_factory=lambda: app, new_slide=True)
        assert r.detail.get("hwnd") == 4242
        added = app.ActivePresentation.Slides(3).Shapes.items
        assert added and all(s.selected for s in added)


def test_PPT_24_select_failure_is_harmless():
    app = FakeApp(with_deck=True)
    import types
    def boom(self, *a):
        raise RuntimeError("window not active")
    Shape.Select, saved = boom, Shape.Select
    try:
        r = send(Picture(IMG), app_factory=lambda: app)
        assert r.added == 1
    finally:
        Shape.Select = saved


def test_PPT_25_sender_reports_the_window():
    app = FakeApp(with_deck=True)
    sender = pp.PowerPointSender(app_factory=lambda: app, timeout=5)
    assert sender.send(Picture(IMG)) == 1 and sender.last_hwnd == 4242



def test_PPT_26_table_becomes_a_native_editable_table():
    app = FakeApp(with_deck=True)
    rows = [["분기", "매출"], ["3분기", "1,250억"], ["4분기", "1,320억"]]
    r = send(TableItem(rows, font_size=14), app_factory=lambda: app)
    shape = app.ActivePresentation.Slides(2).Shapes.items[0]
    assert r.added == 1 and shape.kind == "table" and shape.selected
    assert shape.Table.Rows.Count == 3 and shape.Table.Columns.Count == 2
    cell = shape.Table.Cell(3, 2).Shape.TextFrame.TextRange
    assert cell.Text == "1,320억" and cell.Font.Size == 14 and cell.Font.NameFarEast == "Malgun Gothic"
    assert shape.Left >= 0 and shape.Left + shape.Width <= 960 and shape.Top >= 0


def test_PPT_27_table_is_capped_and_cells_are_single_paragraph_safe():
    app = FakeApp(with_deck=True)
    rows = [[f"{r}-{c}" for c in range(40)] for r in range(300)]
    rows[0][0] = "줄\n바꿈"
    send(TableItem(rows), app_factory=lambda: app)
    t = app.ActivePresentation.Slides(2).Shapes.items[0].Table
    assert t.Rows.Count == pp.MAX_TABLE_ROWS and t.Columns.Count == pp.MAX_TABLE_COLS
    assert t.Cell(1, 1).Shape.TextFrame.TextRange.Text == "줄\r바꿈"


def test_PPT_28_com_is_released_after_every_send(monkeypatch):
    """BUG-017: COM was initialised for each PowerPoint job but never released."""
    import sys
    import types
    calls = []
    fake_com = types.SimpleNamespace(CoInitialize=lambda: calls.append("init"),
                                     CoUninitialize=lambda: calls.append("uninit"))
    monkeypatch.setitem(sys.modules, "pythoncom", fake_com)
    monkeypatch.setattr(pp, "installed", lambda: True)
    app = FakeApp(with_deck=True)
    monkeypatch.setattr(pp, "_real_app", lambda: app)
    send(Picture(IMG))
    with pytest.raises(PowerPointUnavailable):
        monkeypatch.setattr(pp, "_real_app", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        send(Picture(IMG))
    assert calls == ["init", "uninit", "init", "uninit"]


def test_PPT_30_screen_tables_go_in_as_real_tables():
    from capture_tool.core.shapes import ScreenCell, ScreenTable
    t = ScreenTable(x=100, y=200, w=300, h=80, rows=2, cols=3, col_widths=[100, 100, 100], row_heights=[40, 40],
                    line="#B0D2D6",
                    cells=[ScreenCell(0, 0, 1, 2, "은행명", "#EDF8F7", "#111111", 11, True, "ctr"),
                           ScreenCell(0, 2, 1, 1, "계좌번호", "#EDF8F7", "#111111", 11, False, "ctr"),
                           ScreenCell(1, 0, 1, 1, "", None, "#000000", 11, False, "ctr"),
                           ScreenCell(1, 1, 1, 1, "", None, "#000000", 11, False, "ctr"),
                           ScreenCell(1, 2, 1, 1, "", None, "#000000", 11, False, "ctr")])
    app = FakeApp(with_deck=True)
    r = send(ClipboardShapes(tables=[t], origin=(50, 100), dpi=96), app_factory=lambda: app)
    tables = [s for s in app.ActivePresentation.Slides(2).Shapes.items if getattr(s, "HasTable", False)]
    assert len(tables) == 1 and r.added == 4                    # 3 pasted + 1 table
    tb = tables[0]
    assert (tb.Table.Rows.Count, tb.Table.Columns.Count) == (2, 3)
    assert abs(tb.Left - (0 + 50 * 0.75)) < 0.01 and abs(tb.Top - (0 + 100 * 0.75)) < 0.01   # beside the pasted shapes
    assert tb.Table.Cell(1, 1).Shape.TextFrame.TextRange.Text == "은행명"
    assert ("merge", (1, 1), (1, 2)) in app.calls


def test_PPT_31_only_tables_no_paste():
    from capture_tool.core.shapes import ScreenCell, ScreenTable
    t = ScreenTable(x=0, y=0, w=200, h=40, rows=1, cols=2, col_widths=[100, 100], row_heights=[40], line=None,
                    cells=[ScreenCell(0, 0, 1, 1, "a", None, "#000000", 11, False, "ctr"),
                           ScreenCell(0, 1, 1, 1, "b", None, "#000000", 11, False, "ctr")])
    app = FakeApp(with_deck=True)
    r = send(ClipboardShapes(tables=[t], origin=None, dpi=96, paste=False), app_factory=lambda: app)
    assert ("paste",) not in app.calls and r.added == 1
