"""Render real UI screens into docs/images/ for the user guide (headless Qt)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\malgun.ttf")

from capture_tool.app.controller import Controller  # noqa: E402
from capture_tool.app.pin import PinWindow  # noqa: E402
from capture_tool.app.settings_dialog import SettingsDialog  # noqa: E402
from capture_tool.app.text_panel import TextPanel  # noqa: E402
from capture_tool.core.geometry import Monitor, Rect  # noqa: E402
from capture_tool.core.ocr import OcrLine  # noqa: E402
from capture_tool.core.settings import Settings  # noqa: E402
from tests import synth  # noqa: E402
from tests.render import render_text  # noqa: E402
from tests.test_app import FakeClipboard, FakeOcr, FakeScreen  # noqa: E402

OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)


def desktop():
    img = synth.canvas(1280, 720, bg="#E9ECF1")
    synth.rect(img, 60, 40, 1160, 640, fill="#FFFFFF", stroke="#D9DCE1", t=1)
    synth.rect(img, 240, 220, 180, 70, fill="#F1F3F5", radius=10)
    synth.rect(img, 520, 220, 180, 70, fill="#D0EBFF")
    synth.line(img, 422, 255, 516, 255, arrow=True)
    for text, (x, y) in [("업무 프로세스 개요", (90, 70)), ("요청 접수", (285, 235)), ("검토", (585, 235))]:
        t = render_text([text], width=300, size=18)[18:62, 10:290]
        mask = t.min(axis=2) < 128
        img[y:y + 44, x:x + 280][mask] = (40, 35, 31)
    return img


def controller(img):
    tmp = tempfile.mkdtemp()
    mon = Monitor(0, Rect(0, 0, 1280, 720), 1.0, True, "X")
    return Controller(FakeScreen(monitors=[mon], image=img), FakeClipboard(), FakeOcr(), Settings(),
                      os.path.join(tmp, "s.json"), tmp, sync=True)


def drag(w, a, b):
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, QPoint(*a))
    QTest.mouseMove(w, QPoint(*b))
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(*b))


def main():
    img = desktop()
    # 1) selecting
    c = controller(img)
    c.start_capture()
    ov = c.overlays[0]
    ov.resize(1280, 720)
    QTest.mouseMove(ov, QPoint(600, 450))
    ov.grab().save(str(OUT / "01-select.png"))
    # 2) selected + drawing + bars
    drag(ov, (200, 180), (760, 330))
    ov.set_tool("rect")
    drag(ov, (505, 205), (715, 305))
    ov.set_tool("step")
    QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(240, 220))
    ov.grab().save(str(OUT / "02-draw.png"))
    # 3) palette
    tb = ov.toolbar
    tb.palette.refresh()
    tb.palette.adjustSize()
    tb.palette.grab().save(str(OUT / "03-palette.png"))
    c.close_all()
    # 4) text panel
    lines = [OcrLine("업무 프로세스 개요", (0, 0, 200, 20), 0.99), OcrLine("담당: 홍길동 010-1234-5678", (0, 30, 300, 20), 0.98)]
    tp = TextPanel(lines, lambda p: None, True)
    tp.resize(420, 300)
    tp.show()
    tp.grab().save(str(OUT / "04-text.png"))
    # 5) pin
    pin = PinWindow(img[180:330, 200:760].copy(), QPoint(0, 0))
    pin.show()
    QTest.mouseMove(pin, QPoint(pin.width() - 10, 10))
    pin.grab().save(str(OUT / "05-pin.png"))
    # 6) settings
    dlg = SettingsDialog(Settings())
    dlg.show()
    dlg.grab().save(str(OUT / "06-settings.png"))
    print("images in", OUT)


if __name__ == "__main__":
    main()
