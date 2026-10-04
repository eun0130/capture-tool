"""Excel: paste what is on the clipboard (a table in HTML) into Excel, like Ctrl+V - at the
selected cell when Excel is open, or into a new workbook after starting Excel when it is closed.
Without Excel installed the table simply waits on the clipboard. Time-limited, one job at a time."""
from __future__ import annotations

import threading
from typing import Callable

DEFAULT_TIMEOUT = 45.0          # starting Excel can take a while


class ExcelNotOpen(Exception):
    pass


class ExcelMissing(Exception):
    pass


class ExcelUnavailable(Exception):
    pass


def installed() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"):
            return True
    except OSError:
        return False


def _address(cell) -> str:
    """"B3" (not "$B$3")."""
    addr = cell.Address
    if callable(addr):
        addr = addr(False, False)
    return str(addr).replace("$", "")


def _running_app():
    import pythoncom
    import win32com.client
    try:
        return win32com.client.GetActiveObject("Excel.Application")
    except pythoncom.com_error as e:
        raise ExcelNotOpen("Excel이 열려 있지 않습니다.") from e


def _start_app():
    import win32com.client
    app = win32com.client.Dispatch("Excel.Application")
    app.Visible = True
    app.Workbooks.Add()
    return app


def paste_into_excel(running: Callable | None = None, start: Callable | None = None,
                     installed: Callable | None = None, timeout: float = DEFAULT_TIMEOUT) -> str:
    """-> the cell it went to (e.g. "Sheet1!B3"). running() gives the open Excel or raises
    ExcelNotOpen; start() opens Excel with a new workbook; installed() says whether it exists."""
    real = running is None
    running = running or _running_app
    start = start or _start_app
    is_installed = installed or globals()["installed"]
    box: dict = {}

    def work():
        if real:
            import pythoncom
            pythoncom.CoInitialize()
        try:
            try:
                app = running()
                if app.ActiveWorkbook is None:
                    app.Workbooks.Add()
            except ExcelNotOpen:
                if not is_installed():
                    raise ExcelMissing("Excel이 설치되어 있지 않습니다.")
                app = start()                               # closed: open it with a new workbook
            sheet = app.ActiveSheet
            cell = app.ActiveCell
            where = f"{sheet.Name}!{_address(cell)}"
            sheet.Paste()                                   # at the selected cell, like Ctrl+V
            try:
                app.Visible = True
                app.ActiveWindow.Activate()
            except Exception:  # noqa: BLE001 - the paste is done anyway
                pass
            box["where"] = where
        except ExcelMissing as e:
            box["missing"] = e
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
    if "missing" in box:
        raise box["missing"]
    if "error" in box:
        raise ExcelUnavailable(f"Excel에 붙이지 못했습니다: {box['error']}")
    return box.get("where", "")


def paste_into_open_excel(app_factory: Callable | None = None, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Only into an Excel that is already open (no starting)."""
    def never_start():
        raise ExcelNotOpen("Excel이 열려 있지 않습니다.")

    def check():
        app = (app_factory or _running_app)()
        if app.ActiveWorkbook is None:
            raise ExcelNotOpen("Excel에 열린 통합 문서가 없습니다.")
        return app
    try:
        return paste_into_excel(running=check, start=never_start, installed=lambda: True, timeout=timeout)
    except ExcelUnavailable as e:
        if "열려 있지 않" in str(e) or "통합 문서가 없" in str(e):
            raise ExcelNotOpen(str(e)) from e
        raise


class ExcelSender:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
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
            return paste_into_excel(timeout=self.timeout)
        finally:
            self._busy = False
