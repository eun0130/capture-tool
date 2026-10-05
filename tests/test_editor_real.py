"""Real desktop: scroll-capture a real scrolling window, then use the edit window like a normal
capture — real OCR on the tall result (text at the very bottom), draw, copy."""
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]

FLOW = r'''
import sys, time, tempfile
sys.path.insert(0, r"%s")
import numpy as np, cv2
from PySide6.QtWidgets import QApplication, QScrollArea, QLabel
from PySide6.QtCore import Qt, QPoint
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.render import bgr_to_pixmap
from capture_tool.app.services import RealScreen, RealClipboard
from capture_tool.core.clipboard_payload import PNG, UNICODE
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.settings import Settings
from capture_tool.platform import win_clipboard
from tests.tallocr import tall_page
from tests.test_app import drag
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)
area = QScrollArea(); area.setWindowFlags(Qt.WindowStaysOnTopHint)
area.setGeometry(150, 120, 700, 520); area.show()
dpr = area.devicePixelRatioF()
page, want = tall_page(height=int(4200 * dpr), width=int(640 * dpr), every=int(470 * dpr), size=int(22 * dpr))
lab = QLabel(); lab.setPixmap(bgr_to_pixmap(page, dpr))
lab.resize(round(page.shape[1] / dpr), round(page.shape[0] / dpr)); area.setWidget(lab)
pump(0.8)
eng = OcrEngine(); eng._load()
tmp = tempfile.mkdtemp(dir=r"%s")
c = Controller(RealScreen(), RealClipboard(), eng, Settings(save_dir=tmp), tmp + "/s.json", tmp, sync=False)
c.start_capture(); pump(0.4)
vp = area.viewport()
g0 = vp.mapToGlobal(vp.rect().topLeft()); g1 = vp.mapToGlobal(vp.rect().bottomRight())
ov = next(o for o in c.overlays if o.geometry().contains(g0))
a = ov.mapFromGlobal(g0); b = ov.mapFromGlobal(g1)
drag(ov, (a.x() + 2, a.y() + 2), (b.x() - 2, b.y() - 2)); pump(0.3)
ov.side_bar.trigger("scroll")
end = time.time() + 60
while c.editor is None and time.time() < end:
    pump(0.1)
ed = c.editor
print("editor", ed is not None and ed.isVisible(), None if ed is None else ed.canvas.image.shape[:2])
cv = ed.canvas
cv.side_bar.trigger("text")
end = time.time() + 60
while cv.ocr_lines is None and time.time() < end:
    pump(0.1)
raw = win_clipboard.get_format(UNICODE) or b""
text = raw.decode("utf-16-le", "ignore").split(chr(0))[0] if isinstance(raw, bytes) else raw
found = [w for w in want if w.replace(" ", "") in text.replace(" ", "")]
print("ocr_found", len(found), "of", len(want), "last", repr(want[-1]) if want[-1] in text or want[-1].replace(" ", "") in text.replace(" ", "") else "missing")
QTest = __import__("PySide6.QtTest", fromlist=["QTest"]).QTest
cv.ocr_bar.trigger("back"); pump(0.3)                         # back to drawing
cv.set_tool("rect"); cv.set_color("#E03131")
ed.area.verticalScrollBar().setValue(ed.area.verticalScrollBar().maximum()); pump(0.3)
y_local = cv.height() - 120
drag(cv, (40, y_local), (240, y_local + 60)); pump(0.2)
ed.grab().save(tmp + "/editor.png")
cv.side_bar.trigger("copy"); pump(0.5)
png = win_clipboard.get_format(PNG)
img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
red = (img[:, :, 2] > 180) & (img[:, :, 1] < 90) & (img[:, :, 0] < 90)
ys = np.nonzero(red.any(axis=1))[0]
print("copied", img.shape[:2], "red_near_bottom", bool(len(ys)) and ys.min() > img.shape[0] * 0.8, "closed", c.editor is None)
print("shot", tmp + "/editor.png")
c.close_all(); area.close(); pump(0.2)
'''


def _ok(out: str) -> bool:
    lines = {l.split()[0]: l for l in out.splitlines() if l.split()}
    ocr = lines.get("ocr_found", "")
    try:
        n, total = int(ocr.split()[1]), int(ocr.split()[3])
    except (IndexError, ValueError):
        return False
    return ("editor True" in out and n >= total - 1 and "missing" not in ocr
            and "red_near_bottom True closed True" in out)


def test_ED_REAL_01_scroll_capture_then_ocr_draw_copy_in_the_editor(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(FLOW % (ROOT, tmp_path), _ok)
    print(out)
    assert _ok(out), out
