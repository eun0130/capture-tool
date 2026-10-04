"""Word: paste what is on the clipboard (a table in HTML, with its look) at the cursor of the
open document - or a new document when Word has none. Time-limited, one job at a time."""
from __future__ import annotations

import threading
from typing import Callable

DEFAULT_TIMEOUT = 45.0


class WordUnavailable(Exception):
    pass


class WordBusy(Exception):
    pass


def installed() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Winword.exe"):
            return True
    except OSError:
        return False


def _real_app():
    import pythoncom
    import win32com.client
    try:
        return win32com.client.GetActiveObject("Word.Application")     # the person's open Word
    except pythoncom.com_error:
        return win32com.client.Dispatch("Word.Application")


def insert_clipboard(app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT,
                     hook: Callable | None = None, col_widths: list | None = None) -> int:
    """hook(app) runs on the same thread right after the paste (tests read the result there)."""
    real = app_factory is None
    if real and not installed():
        raise WordUnavailable("Word가 설치되어 있지 않습니다.")
    factory = app_factory or _real_app
    box: dict = {}

    def work():
        if real:
            import pythoncom
            pythoncom.CoInitialize()
        try:
            app = factory()
            app.Visible = True
            if int(app.Documents.Count) == 0:
                app.Documents.Add()
            app.Selection.Paste()                      # at the cursor, like Ctrl+V
            _fit_last_table(app, col_widths)
            try:
                app.Activate()
            except Exception:  # noqa: BLE001 - window not ready: the paste is done anyway
                pass
            box["ok"] = 1
            if hook is not None:
                hook(app)
        except BaseException as e:  # noqa: BLE001 - reported to the caller
            box["error"] = e
        finally:
            if real:
                import pythoncom
                pythoncom.CoUninitialize()

    th = threading.Thread(target=work, name="word-insert", daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise WordUnavailable("Word가 응답하지 않습니다(열린 대화 상자가 있는지 확인하세요).")
    if "error" in box:
        raise WordUnavailable(f"Word에 넣지 못했습니다: {box['error']}")
    return box.get("ok", 0)


MIN_COL_PT = 40.0       # a column never narrower than this (short labels like "D1" stay on one line)


def fit_widths(widths: list[float], avail: float) -> list[float]:
    """The capture's column proportions scaled to the page, each at least MIN_COL_PT."""
    if not widths or avail <= 0:
        return list(widths or [])
    k = min(1.0, avail / sum(widths))
    out = [w * k for w in widths]
    short = [i for i, w in enumerate(out) if w < MIN_COL_PT]
    need = sum(MIN_COL_PT - out[i] for i in short)
    for i in short:
        out[i] = MIN_COL_PT
    rest = [i for i in range(len(out)) if i not in short]
    room = sum(out[i] for i in rest)
    if need and room > need:
        for i in rest:
            out[i] -= need * out[i] / room
    return out


def _fit_last_table(app, widths=None) -> None:
    """The table just pasted (the last one before the cursor) gets the capture's column widths,
    fitted to the page."""
    try:
        doc, cur = app.ActiveDocument, int(app.Selection.Start)
        best = None
        for k in range(1, int(doc.Tables.Count) + 1):
            t = doc.Tables(k)
            if int(t.Range.End) <= cur + 2:
                best = t
        if best is None:
            return
        ps = doc.PageSetup
        avail = float(ps.PageWidth - ps.LeftMargin - ps.RightMargin)
        n = int(best.Columns.Count)
        if not widths or len(widths) != n:
            widths = [float(best.Cell(1, c).Width) for c in range(1, n + 1)]
        for c, w in enumerate(fit_widths(list(widths), avail), 1):
            best.Columns(c).SetWidth(w, 0)          # wdAdjustNone
    except Exception:  # noqa: BLE001 - fakes / protected documents / merged cells: the table is in anyway
        pass


class WordSender:
    def __init__(self, app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.app_factory, self.timeout = app_factory, timeout
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def insert(self, col_widths: list | None = None) -> int:
        with self._lock:
            if self._busy:
                raise WordBusy("Word에 넣는 중입니다.")
            self._busy = True
        try:
            return insert_clipboard(self.app_factory, self.timeout, col_widths=col_widths)
        finally:
            self._busy = False
