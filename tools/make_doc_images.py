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


def pin_scene():
    """Illustration: a document window being edited, with a pinned table capture on top."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
    from tests.test_table import excel_like
    from tests.render import _font

    W, H = 1100, 600
    canvas = QImage(W, H, QImage.Format_RGB888)
    canvas.fill(QColor("#E9ECF1"))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing)
    # the window the user is working in
    p.setPen(QPen(QColor("#C9CED6"), 1))
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(QRectF(30, 30, 1040, 540), 8, 8)
    p.setBrush(QColor("#F3F4F6"))
    p.drawRect(QRectF(30, 30, 1040, 40))
    p.setFont(_font(14))
    p.setPen(QColor("#5B616B"))
    p.drawText(50, 56, "월간 보고서 작성 중 (문서 편집 프로그램)")
    p.setPen(QColor("#1F2328"))
    p.setFont(_font(22))
    p.drawText(70, 120, "9월 판매 보고")
    p.setFont(_font(15))
    for i, line in enumerate(["이번 달 사과 판매량은 3상자, 금액은 3,600원입니다.",
                              "배는 재고가 없어 판매되지 않았습니다.",
                              "합계 금액은 3,600원으로 지난달보다 …|"]):
        p.drawText(70, 170 + i * 36, line)
    for i in range(6):
        p.fillRect(QRectF(70, 300 + i * 30, 440 - (i % 3) * 60, 10), QColor("#E4E7EB"))
    # the pinned capture (a spreadsheet), floating on top
    img, _ = excel_like(rows=4, cols=4, cw=110, rh=30)
    tbl = QImage(img.data, img.shape[1], img.shape[0], img.strides[0], QImage.Format_BGR888).copy()
    tp = QPainter(tbl)
    tp.setFont(_font(13))
    tp.setPen(QColor("black"))
    rows = [["품목", "수량", "단가", "금액"], ["사과", "3", "1,200", "3,600"], ["배", "", "2,500", "0"],
            ["합계", "", "", "3,600"]]
    for r, row in enumerate(rows):
        for c, t in enumerate(row):
            tp.drawText(QRectF(10 + c * 110 + 6, 10 + r * 30, 98, 30), 0x0082 if c else 0x0081, t)
    tp.end()
    x, y = 590, 150
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawRoundedRect(QRectF(x + 6, y + 8, tbl.width(), tbl.height()), 4, 4)   # shadow
    p.drawImage(x, y, tbl)
    p.setPen(QPen(QColor("#1F5FD1"), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(x, y, tbl.width(), tbl.height()))
    cx, cy = x + tbl.width() - 16, y + 16
    p.setBrush(QColor(15, 18, 24, 200))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(cx - 12, cy - 12, 24, 24))
    p.setPen(QPen(QColor("white"), 2))
    p.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
    p.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)
    # callouts
    def note(tx, ty, text):
        f = _font(14)
        f.setBold(True)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 24
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1F5FD1"))
        p.drawRoundedRect(QRectF(tx, ty, w, 32), 16, 16)
        p.setPen(QColor("white"))
        p.drawText(QRectF(tx, ty, w, 32), 0x0084, text)
    note(590, 100, "① 고정한 캡처: 항상 맨 위에 떠 있음")
    note(590, 325, "② 끌어서 옮기기 · Esc나 X로 닫기")
    note(70, 505, "③ 아래 창에서는 평소처럼 글을 쓰고 클릭할 수 있음")
    p.end()
    return canvas


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
    # 3) palette (color + thickness slider)
    tb = ov.toolbar
    tb.palette.refresh()
    tb.palette.adjustSize()
    tb.palette.grab().save(str(OUT / "03-palette.png"))
    # 3b) text tool with its style controls
    ov.set_tool("text")
    tb.toggle_style("bold")
    tb.arrange(1280)
    tb.grab().save(str(OUT / "07-text-style.png"))
    c.close_all()
    # 3c) text mode: drag over part of the recognized text
    lines = [OcrLine("업무 프로세스 개요", (90 - 200, 70 - 180, 280, 44), 0.99)]
    c = controller(img)
    c.ocr = FakeOcr([OcrLine("요청 접수", (85, 55, 110, 30), 0.99), OcrLine("검토", (385, 55, 60, 30), 0.99)])
    c.start_capture()
    ov = c.overlays[0]
    ov.resize(1280, 720)
    drag(ov, (200, 180), (760, 330))
    ov.side_bar.trigger("text")
    drag(ov, (280, 230), (400, 270))
    ov.grab().save(str(OUT / "08-text-mode.png"))
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
    # 5b) how pinning is used: a pinned table floats over the window you are typing in
    pin_scene().save(str(OUT / "09-pin-usage.png"))
    # 6) settings
    dlg = SettingsDialog(Settings())
    dlg.show()
    dlg.grab().save(str(OUT / "06-settings.png"))
    print("images in", OUT)


if __name__ == "__main__":
    main()
