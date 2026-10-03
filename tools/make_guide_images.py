"""Pictures for the beginner's guide, made from the app's own widgets over a made-up screen (no
real desktop, nothing personal). Writes capture_tool/app/guide_images/ and docs/images/guide/.
Run after changing how those parts look: python tools/make_guide_images.py"""
import os
import shutil
import sys
from pathlib import Path

REAL_PIN = "--real-pin" in sys.argv        # the pin bar uses symbols the offscreen font lacks
if not REAL_PIN:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
for f in ("malgun.ttf", "malgunbd.ttf", "segoeui.ttf", "seguisym.ttf"):
    QFontDatabase.addApplicationFont(rf"C:\Windows\Fonts\{f}")
FAMILY = "Malgun Gothic"

from capture_tool.app.controller import Controller  # noqa: E402
from capture_tool.core.geometry import Monitor, Rect  # noqa: E402
from capture_tool.core.settings import Settings  # noqa: E402
from tests.test_app import FakeClipboard, FakeOcr, FakeScreen, drag  # noqa: E402

OUT_PKG = ROOT / "capture_tool" / "app" / "guide_images"
OUT_DOC = ROOT / "docs" / "images" / "guide"
W, H = 1100, 700
MAX_W = 760


def qimage_to_bgr(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
    return a.reshape(img.height(), img.width(), 3)[:, :, ::-1].copy()


def fake_screen() -> np.ndarray:
    """A made-up report page with a table."""
    img = QImage(W, H, QImage.Format_RGB888)
    img.fill(QColor("#F3F5F8"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(QRect(0, 0, W, 48), QColor("#2B3A55"))
    f = QFont(FAMILY)
    f.setPixelSize(18)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(24, 31, "주간 업무 보고")
    p.fillRect(QRect(60, 80, 980, 560), QColor("#FFFFFF"))
    f.setPixelSize(20)
    p.setFont(f)
    p.setPen(QColor("#1D2330"))
    p.drawText(100, 128, "3분기 판매 현황")
    f.setBold(False)
    f.setPixelSize(16)
    p.setFont(f)
    rows = [("제품", "수량", "매출", "비고"), ("노트북", "120", "1억 5천만", "영업팀"), ("모니터", "300", "9,600만", ""),
            ("키보드", "450", "1,575만", "무선"), ("마우스", "500", "900만", "신제품")]
    x0, y0, cw, rh = 100, 160, 200, 44
    for r, row in enumerate(rows):
        if r == 0:
            p.fillRect(QRect(x0, y0, cw * 4, rh), QColor("#E8EEF8"))
        for c, val in enumerate(row):
            p.setPen(QColor("#C9D1DC"))
            p.drawRect(QRect(x0 + c * cw, y0 + r * rh, cw, rh))
            p.setPen(QColor("#1D2330"))
            p.drawText(QRect(x0 + c * cw + 12, y0 + r * rh, cw - 20, rh), Qt.AlignVCenter, val)
    p.setPen(QColor("#5B6472"))
    p.drawText(100, 430, "다음 주 계획: 신제품 출시 준비, 거래처 방문 3곳")
    p.end()
    return qimage_to_bgr(img)


def controller(settings=None):
    mon = Monitor(0, Rect(0, 0, W, H), 1.0, True, "A")
    c = Controller(FakeScreen(monitors=(mon,), image=fake_screen()), FakeClipboard(), FakeOcr(), settings or Settings(),
                   ROOT / "build" / "guide_settings.json", ROOT / "build" / "guide_shots", sync=True)
    return c


def shrink(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= MAX_W:
        return img
    return cv2.resize(img, (MAX_W, round(h * MAX_W / w)), interpolation=cv2.INTER_AREA)


def save(name: str, img: np.ndarray) -> None:
    OUT_PKG.mkdir(parents=True, exist_ok=True)
    OUT_DOC.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", shrink(img), [cv2.IMWRITE_PNG_COMPRESSION, 9])
    (OUT_PKG / name).write_bytes(buf.tobytes())
    shutil.copyfile(OUT_PKG / name, OUT_DOC / name)
    print("wrote", name)


def grab(widget, rect: QRect | None = None) -> np.ndarray:
    return qimage_to_bgr((widget.grab(rect) if rect else widget.grab()).toImage())


def capture_shot(expanded: bool):
    s = Settings()
    s.bar_expanded = expanded
    c = controller(s)
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (90, 150), (910, 385))
    ov.show_toolbar()
    app.processEvents()
    img = grab(ov)
    c.close_all()
    return img


def main() -> None:
    full = capture_shot(False)
    save("capture.png", full[96:560, 60:1060])
    wide = capture_shot(True)
    save("bar_full.png", wide[388:500, 80:900])

    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}     # real windows for these
    subprocess.run([sys.executable, __file__, "--real-pin"], check=True, env=env)


def pin_shot() -> None:
    from capture_tool.app.table_options import TableOptions
    d = TableOptions(Settings())
    d.show()
    app.processEvents()
    save("table_options.png", grab(d))
    d.close()

    from capture_tool.app.mail_ui import MailHelper
    h = MailHelper(lambda payload: True)
    h.set_data(["boss@example.com"], ["team1@example.com", "team2@example.com"], "캡처 공유 — 10월 3일 14:40",
               True, {"PNG": b""}, lambda: None)
    h.resize(380, h.sizeHint().height())
    h.show()
    app.processEvents()
    save("mail_helper.png", grab(h))
    h.close()

    from capture_tool.app.pin import PinWindow
    pin = PinWindow(fake_screen()[150:390, 90:910], QPoint(0, 0))
    pin.zoom = 0.6
    pin._resize()
    pin.show()
    pin._place_bar()
    pin.hover_bar.show()
    app.processEvents()
    save("pin.png", grab(pin))
    pin.close()


if __name__ == "__main__":
    pin_shot() if REAL_PIN else main()
