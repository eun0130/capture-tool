"""Put a capture into PowerPoint — the slide being viewed, or a new deck.

Safety rules (a frozen or busy PowerPoint must never freeze this app):
- only the document object model is used (AddPicture / AddTextbox / Shapes.Paste); no window
  activation, view switching or UI commands, which wait on PowerPoint's UI thread;
- every job runs in its own thread with a time limit; one job at a time."""
from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

PP_LAYOUT_BLANK = 12
MSO_TEXT_HORIZONTAL = 1
DEFAULT_TIMEOUT = 15.0
FIT = 0.9  # a big picture is shrunk to 90 % of the slide


class PowerPointUnavailable(RuntimeError):
    pass


class PowerPointTimeout(PowerPointUnavailable):
    pass


class PowerPointBusy(RuntimeError):
    pass


@dataclass
class Picture:
    image: np.ndarray          # BGR
    dpi: float = 96            # screen pixels per inch (96 × Windows scale) -> on-screen size


@dataclass
class TextItem:
    text: str
    font_family: str = "Malgun Gothic"
    font_size: float = 18      # points


# PowerPoint lays out a text box synchronously; tens of thousands of characters (a huge
# tab-separated "table") keep it busy for minutes and it shows "응답 없음".
MAX_TEXT_CHARS = 5000


def clip_text(text: str, limit: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    """(text cut at a line boundary to at most `limit` chars + "…", whether it was cut)."""
    if len(text) <= limit:
        return text, False
    head = text[:limit - 2]
    nl = head.rfind("\n")
    if nl > 0:
        head = head[:nl]
    return head.rstrip() + "\n…", True


@dataclass
class TableItem:
    """Rows of cell text -> a native PowerPoint table (each cell editable)."""
    rows: list
    font_family: str = "Malgun Gothic"
    font_size: float = 14      # points


# every cell is one COM round trip; a slide can't show more anyway
MAX_TABLE_ROWS = 50
MAX_TABLE_COLS = 15


def table_fits(rows: list) -> bool:
    return bool(rows) and len(rows) <= MAX_TABLE_ROWS and max(len(r) for r in rows) <= MAX_TABLE_COLS


@dataclass
class ClipboardShapes:
    """Native shapes already on the clipboard (Art::GVML ClipFormat)."""


@dataclass
class SendResult:
    added: int
    detail: dict = field(default_factory=dict)


def installed() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE"):
            return True
    except OSError:
        return False


def _real_app():
    import pythoncom
    import win32com.client
    try:
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except pythoncom.com_error:
        return win32com.client.Dispatch("PowerPoint.Application")


def place(w: float, h: float, slide_w: float, slide_h: float) -> tuple[float, float, float, float]:
    """(left, top, width, height) centered on the slide, shrunk to fit if needed."""
    w, h = max(w, 1.0), max(h, 1.0)
    k = min(1.0, slide_w * FIT / w, slide_h * FIT / h)
    w, h = w * k, h * k
    return (slide_w - w) / 2, (slide_h - h) / 2, w, h


def _current_slide(app, pres):
    """The slide the user is looking at, else the last one, else None (empty deck)."""
    try:
        return app.ActiveWindow.View.Slide
    except Exception:  # noqa: BLE001 - slide sorter, slide show, no window …
        return pres.Slides(pres.Slides.Count) if pres.Slides.Count else None


def _target_slide(app, new_presentation: bool, new_slide: bool = False):
    app.Visible = True
    if new_presentation or app.Presentations.Count == 0:
        pres = app.Presentations.Add()
        return pres, pres.Slides.Add(1, PP_LAYOUT_BLANK)   # fresh deck: its first slide is new already
    pres = app.ActivePresentation
    cur = _current_slide(app, pres)
    if cur is None:
        return pres, pres.Slides.Add(1, PP_LAYOUT_BLANK)
    if not new_slide:
        return pres, cur
    index = int(cur.SlideIndex) + 1                          # right after the one being viewed
    slide = pres.Slides.Add(index, PP_LAYOUT_BLANK)
    try:
        app.ActiveWindow.View.GotoSlide(index)              # show it (best effort)
    except Exception:  # noqa: BLE001
        pass
    return pres, slide


def _insert(app, item, new_presentation: bool, hook, new_slide: bool = False) -> SendResult:
    pres, slide = _target_slide(app, new_presentation, new_slide)
    sw, sh = float(pres.PageSetup.SlideWidth), float(pres.PageSetup.SlideHeight)
    if isinstance(item, Picture):
        import cv2
        h, w = item.image.shape[:2]
        left, top, pw, ph = place(w * 72 / item.dpi, h * 72 / item.dpi, sw, sh)
        fd, path = tempfile.mkstemp(prefix="capture_", suffix=".png")
        os.close(fd)
        try:
            ok, buf = cv2.imencode(".png", item.image, [cv2.IMWRITE_PNG_COMPRESSION, 1])   # fast; temp file
            buf.tofile(path)
            new = slide.Shapes.AddPicture(path, False, True, left, top, pw, ph)
        finally:
            try:
                os.remove(path)  # our own temporary file
            except OSError:
                pass
        added = 1
    elif isinstance(item, TextItem):
        text, _ = clip_text(item.text.replace("\r\n", "\n"))
        lines = text.split("\n")
        tw = min(sw * FIT, max(200.0, max(len(l) for l in lines) * item.font_size * 1.05))
        th = min(sh * FIT, len(lines) * item.font_size * 1.6 + 10)
        left, top, tw, th = place(tw, th, sw, sh)
        box = new = slide.Shapes.AddTextbox(MSO_TEXT_HORIZONTAL, left, top, tw, th)
        rng = box.TextFrame.TextRange
        rng.Text = "\r".join(lines)          # PowerPoint paragraphs are separated by \r
        rng.Font.Name = item.font_family
        rng.Font.NameFarEast = item.font_family
        rng.Font.Size = item.font_size
        added = 1
    elif isinstance(item, TableItem):
        rows = [list(r)[:MAX_TABLE_COLS] for r in item.rows[:MAX_TABLE_ROWS]]
        nr, nc = len(rows), max(len(r) for r in rows)
        widest = [max((len(r[c]) if c < len(r) else 0) for r in rows) for c in range(nc)]
        tw = min(sw * FIT, max(120.0 * nc, sum(max(4, w) * item.font_size * 0.9 for w in widest)))
        th = min(sh * FIT, nr * item.font_size * 2.0)
        left, top, tw, th = place(tw, th, sw, sh)
        new = slide.Shapes.AddTable(nr, nc, left, top, tw, th)
        table = new.Table
        for r, row in enumerate(rows, 1):
            for c in range(1, nc + 1):
                rng = table.Cell(r, c).Shape.TextFrame.TextRange
                cell = row[c - 1] if c <= len(row) else ""
                rng.Text = cell.replace("\r\n", "\r").replace("\n", "\r")     # PowerPoint paragraphs
                rng.Font.Name = item.font_family
                rng.Font.NameFarEast = item.font_family
                rng.Font.Size = item.font_size
        added = 1
    elif isinstance(item, ClipboardShapes):
        new = slide.Shapes.Paste()
        added = int(new.Count)
    else:
        raise TypeError(f"unknown item {item!r}")
    try:
        app.Activate()  # bring PowerPoint forward (best effort; our app also raises it)
    except Exception:  # noqa: BLE001
        pass
    try:
        new.Select()    # what was just added is selected: easy to see, move or delete
    except Exception:  # noqa: BLE001 - slide sorter view, window not ready …
        pass
    try:
        hwnd = int(app.HWND)                  # fakes in tests; PowerPoint itself has no HWND
    except Exception:  # noqa: BLE001
        try:
            hwnd = find_window(str(pres.Windows(1).Caption))
        except Exception:  # noqa: BLE001
            hwnd = 0
    if hook is not None:
        hook(pres, slide, added)
    return SendResult(added, {"hwnd": hwnd})


def send(item, app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT,
         new_presentation: bool = False, hook: Callable | None = None, new_slide: bool = False) -> SendResult:
    """Insert `item`; never blocks longer than `timeout` seconds."""
    real = app_factory is None
    if real and not installed():
        raise PowerPointUnavailable("PowerPoint가 설치되어 있지 않습니다.")
    factory = app_factory or _real_app
    box: dict = {}

    def work():
        if real:
            import pythoncom
            pythoncom.CoInitialize()
        try:
            box["result"] = _insert(factory(), item, new_presentation, hook, new_slide)
        except BaseException as e:  # noqa: BLE001 - reported to the caller
            box["error"] = e
        finally:
            if real:
                import pythoncom
                pythoncom.CoUninitialize()

    th = threading.Thread(target=work, name="powerpoint-send", daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise PowerPointTimeout(f"PowerPoint가 {timeout:.0f}초 동안 응답하지 않습니다.")
    err = box.get("error")
    if isinstance(err, PowerPointUnavailable):
        raise err
    if err is not None:
        raise PowerPointUnavailable(f"PowerPoint에 넣지 못했습니다: {err}") from err
    return box["result"]


class PowerPointSender:
    """Controller-facing: one job at a time; returns the number of shapes added."""

    def __init__(self, app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.app_factory = app_factory
        self.timeout = timeout
        self._lock = threading.Lock()
        self._busy = False
        self.new_slide = True      # each capture on its own new slide after the current one
        self.last_hwnd = 0         # PowerPoint's window after the last insert (to bring it forward)

    @property
    def busy(self) -> bool:
        return self._busy

    def send(self, item) -> int:
        with self._lock:
            if self._busy:
                raise PowerPointBusy("PowerPoint로 보내는 중입니다.")
            self._busy = True
        try:
            r = send(item, self.app_factory, self.timeout, new_slide=self.new_slide)
            self.last_hwnd = int(r.detail.get("hwnd") or 0)
            return r.added
        finally:
            self._busy = False



def find_window(caption: str) -> int:
    """PowerPoint's document window (class PPTFrameClass) whose title starts with `caption`."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[int] = []

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, cls, 64)
        if cls.value == "PPTFrameClass" and u32.IsWindowVisible(h):
            title = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(h, title, 512)
            if title.value.startswith(caption):
                found.append(int(h))
        return True
    u32.EnumWindows(proc(cb), 0)
    return found[0] if found else 0


def bring_to_front(hwnd: int) -> bool:
    """Show PowerPoint in front, active. Called from the capture tool's own UI thread, which
    received the user's last click, so Windows allows the switch; Alt is tapped as a fallback
    (Windows lets the foreground change after a key press). True if it worked."""
    import ctypes
    from ctypes import wintypes
    if not hwnd:
        return False
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.IsIconic.argtypes = [wintypes.HWND]
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.BringWindowToTop.argtypes = [wintypes.HWND]
    u32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    SW_RESTORE, SW_SHOW, ASFW_ANY = 9, 5, 0xFFFFFFFF
    u32.ShowWindow(hwnd, SW_RESTORE if u32.IsIconic(hwnd) else SW_SHOW)
    u32.AllowSetForegroundWindow(ASFW_ANY)
    if u32.SetForegroundWindow(hwnd) and int(u32.GetForegroundWindow() or 0) == hwnd:
        return True
    VK_MENU, KEYUP = 0x12, 0x0002
    u32.keybd_event(VK_MENU, 0, 0, 0)
    u32.keybd_event(VK_MENU, 0, KEYUP, 0)
    u32.SetForegroundWindow(hwnd)
    u32.BringWindowToTop(hwnd)
    return int(u32.GetForegroundWindow() or 0) == hwnd
