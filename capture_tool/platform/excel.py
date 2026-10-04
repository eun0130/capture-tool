"""Excel: when Excel is already open, paste what is on the clipboard (a table in HTML) at the
selected cell of the open sheet, like Ctrl+V. Excel is never started for this - when it isn't
running the table simply waits on the clipboard. Time-limited, one job at a time."""
from __future__ import annotations

import threading
from typing import Callable

DEFAULT_TIMEOUT = 30.0


class ExcelNotOpen(Exception):
    pass


class ExcelUnavailable(Exception):
    pass


def _running_app():
    import pythoncom
    import win32com.client
    try:
        return win32com.client.GetActiveObject("Excel.Application")
    except pythoncom.com_error as e:
        raise ExcelNotOpen("Excel이 열려 있지 않습니다.") from e


def paste_into_open_excel(app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT) -> str:
    """-> the cell it went to (e.g. "Sheet1!B3")."""
    real = app_factory is None
    factory = app_factory or _running_app
    box: dict = {}

    def work():
        if real:
            import pythoncom
            pythoncom.CoInitialize()
        try:
            app = factory()
            if app.ActiveWorkbook is None:
                raise ExcelNotOpen("Excel에 열린 통합 문서가 없습니다.")
            sheet = app.ActiveSheet
            cell = app.ActiveCell
            where = f"{sheet.Name}!{cell.Address(False, False)}"
            sheet.Paste()                                   # at the selected cell, like Ctrl+V
            try:
                app.Visible = True
                app.ActiveWindow.Activate()
            except Exception:  # noqa: BLE001 - the paste is done anyway
                pass
            box["where"] = where
        except ExcelNotOpen as e:
            box["not_open"] = e
        except BaseException as e:  # noqa: BLE001 - reported to the caller
            box["error"] = e
        finally:
            if real:
                import pythoncom
                pythoncom.CoUninitialize()

    th = threading.Thread(target=work, name="excel-paste", daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise ExcelUnavailable("Excel이 응답하지 않습니다(셀을 편집 중이거나 대화 상자가 열려 있는지 확인하세요).")
    if "not_open" in box:
        raise box["not_open"]
    if "error" in box:
        raise ExcelUnavailable(f"Excel에 붙이지 못했습니다: {box['error']}")
    return box.get("where", "")


class ExcelSender:
    def __init__(self, app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.app_factory, self.timeout = app_factory, timeout
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def paste(self) -> str:
        with self._lock:
            if self._busy:
                raise ExcelUnavailable("Excel에 붙이는 중입니다.")
            self._busy = True
        try:
            return paste_into_open_excel(self.app_factory, self.timeout)
        finally:
            self._busy = False
