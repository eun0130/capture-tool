"""Leak soak: run each feature many times in one real process and report how memory, GDI/USER
handles, kernel handles, threads and Qt windows change. Used by tests/test_leaks_real.py and
runnable alone: python tests/soak.py [rounds]"""
from __future__ import annotations

import ctypes
import gc
import json
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

k32 = ctypes.WinDLL("kernel32")
u32 = ctypes.WinDLL("user32")
psapi = ctypes.WinDLL("psapi")
k32.GetCurrentProcess.restype = wintypes.HANDLE
u32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
               [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]


def stats(app) -> dict:
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(3):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()
    from PySide6.QtWidgets import QApplication
    h = k32.GetCurrentProcess()
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    hc = wintypes.DWORD()
    k32.GetProcessHandleCount(h, ctypes.byref(hc))
    import threading
    return {"private_mb": round(pmc.PagefileUsage / 2**20, 1), "gdi": u32.GetGuiResources(h, 0),
            "user": u32.GetGuiResources(h, 1), "handles": hc.value, "py_threads": threading.active_count(),
            "top_widgets": len(QApplication.topLevelWidgets())}


def main(rounds: int = 30) -> dict:
    import numpy as np
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QThreadPool
    from capture_tool.app.controller import Controller
    from capture_tool.app.services import RealClipboard, RealScreen
    from capture_tool.app.toast import Toast
    from capture_tool.core.ai_service import AiResult
    from capture_tool.core.ocr import OcrEngine
    from capture_tool.core.settings import Settings
    from tests.scrollsim import make_page
    from tests.test_app import FakePpt, drag

    def pump(sec=0.0):
        end = time.perf_counter() + sec
        app.processEvents()
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)
        QThreadPool.globalInstance().waitForDone(5000)
        app.processEvents()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)   # what the real event loop does

    tmp = tempfile.mkdtemp()
    eng = OcrEngine()
    eng._load()
    toast = Toast()
    c = Controller(RealScreen(), RealClipboard(), eng, Settings(save_dir=tmp, auto_save=True), tmp + "/s.json", tmp,
                   sync=False, notify=toast.show_message)
    c.prewarm()
    c.powerpoint = FakePpt()
    c.powerpoint.items = type("NoKeep", (list,), {"append": lambda self, x: None})()   # fake keeps nothing

    class FakeAi:
        busy = False

        def translate(self, text, src=None, tgt=None, cancel=None):
            return AiResult("번역 " + text[:20], "local", "ko", "en")

        def summarize(self, text, lang="ko", on_text=None, cancel=None):
            return AiResult("• 요약", "local", tgt=lang)

        def preload(self, text):
            pass

        def unload(self):
            pass
    c.ai = FakeAi()

    def selected():
        c.start_capture()
        pump(0.05)
        ov = c.active_overlay or c.overlays[0]
        drag(ov, (200, 200), (900, 700))
        pump()
        return ov

    def cycle_copy():
        ov = selected()
        ov.set_tool("rect")
        drag(ov, (250, 250), (400, 350))
        ov.set_tool("text")
        QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(300, 400))
        if ov._editor is not None:
            ov._editor.insert("abc")
        ov.side_bar.trigger("copy")
        pump(0.02)

    def cycle_text():
        ov = selected()
        ov.side_bar.trigger("text")
        end = time.time() + 10
        while ov.ocr_lines is None and time.time() < end and c.overlays:
            pump(0.02)
        ov.ocr_bar.trigger("translate")
        pump(0.05)
        if c.ai_window is not None:
            c.ai_window.close()
        QTest.keyClick(ov, Qt.Key_Escape)
        QTest.keyClick(ov, Qt.Key_Escape)
        pump(0.02)

    def cycle_pin():
        ov = selected()
        ov.side_bar.trigger("pin")
        pump(0.05)
        c.close_pins()
        pump(0.02)

    def cycle_ppt():
        ov = selected()
        ov.side_bar.trigger("ppt")
        pump(0.05)

    big = make_page(6000, w=1200)

    def cycle_editor():
        c.open_editor(big, 96, "soak")
        pump(0.05)
        cv = c.editor.canvas
        cv.set_tool("mosaic")
        drag(cv, (20, 20), (200, 120))
        c.editor.set_zoom(2.0)
        c.editor.fit_width()
        QTest.keyClick(cv, Qt.Key_Escape)
        pump(0.02)

    cycles = [("copy", cycle_copy), ("text", cycle_text), ("pin", cycle_pin), ("ppt", cycle_ppt),
              ("editor", cycle_editor)]
    for _, fn in cycles:                      # warm-up: first use loads caches, fonts, models
        fn()
        fn()
    pump(0.2)
    base = stats(app)
    per: dict[str, dict] = {}
    for name, fn in cycles:
        before = stats(app)
        for _ in range(rounds):
            fn()
        pump(0.1)
        after = stats(app)
        per[name] = {k: round(after[k] - before[k], 1) for k in after}
    end = stats(app)
    c.close_all()
    toast.close()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)   # the soak's own temporary save folder
    return {"rounds": rounds, "base": base, "end": end, "per_feature": per}


if __name__ == "__main__":
    out = main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    print("SOAK " + json.dumps(out, ensure_ascii=False))
