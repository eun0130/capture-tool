"""Real desktop: capture real text on screen -> 텍스트 -> 번역 with the real offline model; the key
wizard notices a key copied to the real Windows clipboard."""
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.slow,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
ROOT = Path(__file__).resolve().parents[1]

FLOW = r'''
import sys, time, tempfile
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen, RealClipboard
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.settings import Settings
from tests.test_app import drag
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
lab = QLabel("The meeting starts at three tomorrow.")
f = QFont("Arial"); f.setPixelSize(34); lab.setFont(f)
lab.setStyleSheet("background:white; color:black; padding:20px")
lab.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
lab.move(200, 200); lab.show(); pump(0.8)
tmp = tempfile.mkdtemp(dir=r"%s")
eng = OcrEngine(); eng._load()
c = Controller(RealScreen(), RealClipboard(), eng, Settings(), tmp + "/s.json", tmp, sync=True)
c.start_capture(); pump(0.3)
g = lab.geometry()
ov = next(o for o in c.overlays if o.geometry().contains(g.center()))   # the monitor showing the text
tl = ov.mapFromGlobal(g.topLeft()); br = ov.mapFromGlobal(g.bottomRight())
drag(ov, (tl.x() - 5, tl.y() - 5), (br.x() + 5, br.y() + 5)); pump(0.2)
ov.side_bar.trigger("text"); pump(0.5)
print("ocr", repr(c._last_raw))
ov.ocr_bar.trigger("translate"); pump(0.3)
print("result", repr(c.ai_window.result_text()), "|", c.ai_window.status_text())
c.close_all(); lab.close(); pump(0.2)
'''


def _flow_ok(out: str) -> bool:
    line = next((l for l in out.splitlines() if l.startswith("result")), "")
    return ("회의" in line or "미팅" in line) and "오프라인" in line


def test_AIU_REAL_01_capture_text_translate_with_offline_model(tmp_path):
    from capture_tool.core import model_store as ms
    if not ms.installed_dir(ms.CATALOG["mt-en_ko"]):
        pytest.skip("en->ko pack not installed")
    from tests.conftest import run_on_desktop
    out = run_on_desktop(FLOW % (ROOT, tmp_path), _flow_ok)
    assert _flow_ok(out), out


KEY_FLOW = r'''
import sys, time
sys.path.insert(0, r"%s")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.app.ai_ui import KeyDialog
from capture_tool.core.settings import Settings
from capture_tool.platform import win_clipboard
from capture_tool.core.clipboard_payload import UNICODE
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
KEY = "AIza" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"
seen = []
d = KeyDialog(Settings(), open_url=lambda u: None, check=seen.append)
d.show(); pump(0.3)
win_clipboard.set_formats({UNICODE: "copied: " + KEY}, retries=10, delay=0.02)
pump(1.5)
print("seen", seen == [KEY], "label", d.key_label.text())
win_clipboard.set_formats({UNICODE: ""}, retries=10, delay=0.02)   # don't leave the fake key on the clipboard
d.close(); pump(0.1)
'''


def test_AIU_REAL_02_key_copied_in_the_browser_is_picked_up(tmp_path):
    from tests.conftest import run_on_desktop
    ok = lambda o: "seen True" in o
    out = run_on_desktop(KEY_FLOW % ROOT, ok)
    assert ok(out), out
