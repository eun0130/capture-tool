"""Open PowerPoint (or use the running one) and paste the clipboard into the current slide."""
from __future__ import annotations

import time
from dataclasses import dataclass

PP_LAYOUT_BLANK = 12
PP_VIEW_NORMAL = 9


class PowerPointUnavailable(RuntimeError):
    pass


@dataclass
class PasteResult:
    presentation: object
    slide: object
    added: int


def installed() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE"):
            return True
    except OSError:
        return False


def _app():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        return win32com.client.GetActiveObject("PowerPoint.Application")
    except pythoncom.com_error:
        return win32com.client.Dispatch("PowerPoint.Application")


def paste(new_presentation: bool = False, timeout: float = 5.0) -> PasteResult:
    """Paste into the slide the user is looking at (a new blank deck if none is open)."""
    if not installed():
        raise PowerPointUnavailable("PowerPoint가 설치되어 있지 않습니다.")
    try:
        app = _app()
        app.Visible = True
        if new_presentation or app.Presentations.Count == 0:
            pres = app.Presentations.Add()
            slide = pres.Slides.Add(1, PP_LAYOUT_BLANK)
            win = pres.Windows(1)
        else:
            win = app.ActiveWindow
            pres = win.Presentation
            try:
                slide = win.View.Slide
            except Exception:  # noqa: BLE001 - no current slide in this view
                slide = pres.Slides(pres.Slides.Count) if pres.Slides.Count else pres.Slides.Add(1, PP_LAYOUT_BLANK)
        win.Activate()
        win.ViewType = PP_VIEW_NORMAL
        win.View.GotoSlide(slide.SlideIndex)
        win.Panes(2).Activate()
        before = slide.Shapes.Count
        app.CommandBars.ExecuteMso("Paste")
        deadline = time.monotonic() + timeout
        while slide.Shapes.Count == before and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            app.Activate()
        except Exception:  # noqa: BLE001 - bringing the window forward is best effort
            pass
        return PasteResult(pres, slide, slide.Shapes.Count - before)
    except PowerPointUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 - COM errors vary; report as unavailable
        raise PowerPointUnavailable(f"PowerPoint에 붙여넣지 못했습니다: {e}") from e


class PowerPointSender:
    """Controller-facing wrapper; returns the number of shapes added."""

    def paste(self) -> int:
        import pythoncom
        try:
            result = paste()
            added = result.added
            del result  # release COM references before leaving this thread's apartment
            return added
        finally:
            pythoncom.CoUninitialize()
