"""Real desktop: the user's reports — capture -> 요약 -> PPT로 "did nothing" (it worked behind the
capture screen) and 표로 복사 "did nothing" (no visible confirmation)."""
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
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen, RealClipboard
from capture_tool.app.toast import Toast
from capture_tool.core.ai_service import AiResult
from capture_tool.core.clipboard_payload import HTML
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.settings import Settings
from capture_tool.platform import win_clipboard
from tests.test_app import FakePpt, drag
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)
lab = QLabel("품목    수량\n사과    3\n배      5")
f = QFont("Malgun Gothic"); f.setPixelSize(30); lab.setFont(f)
lab.setStyleSheet("background:white; color:black; padding:20px")
lab.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
lab.move(200, 200); lab.show(); pump(0.8)
tmp = tempfile.mkdtemp(dir=r"%s")
eng = OcrEngine(); eng._load()
toast = Toast()
c = Controller(RealScreen(), RealClipboard(), eng, Settings(), tmp + "/s.json", tmp, sync=False,
               notify=toast.show_message)
class FakeAi:
    busy = False
    def summarize(self, text, lang="ko", on_text=None, cancel=None):
        return AiResult("• 사과 3, 배 5", "local", tgt="ko")
    def unload(self): pass
c.ai = FakeAi()
ppt = FakePpt(); c.powerpoint = ppt
c.start_capture(); pump(0.4)
g = lab.geometry()
ov = next(o for o in c.overlays if o.geometry().contains(g.center()))
tl = ov.mapFromGlobal(g.topLeft()); br = ov.mapFromGlobal(g.bottomRight())
drag(ov, (tl.x() - 5, tl.y() - 5), (br.x() + 5, br.y() + 5)); pump(0.2)
ov.side_bar.trigger("text"); pump(3)
ov.ocr_bar.trigger("summarize"); pump(1)
win = c.ai_window
win.trigger("ppt"); pump(1.5)
print("ppt_sent", len(ppt.items), "win_visible", win.isVisible(), "overlays", len(c.overlays),
      "toast", toast.isVisible(), repr(toast.label.text()))
# text window: 표로 복사
c.start_capture(); pump(0.4)
ov = next(o for o in c.overlays if o.geometry().contains(g.center()))
drag(ov, (tl.x() - 5, tl.y() - 5), (br.x() + 5, br.y() + 5)); pump(0.2)
ov.side_bar.trigger("text"); pump(3)
ov.ocr_bar.trigger("window"); pump(0.5)
panel = c.text_panel
panel.copy_table(); pump(0.3)
html = win_clipboard.get_format(HTML) or b""
print("table_status", repr(panel.status.text()), "html_table", b"<table>" in html, "toast", toast.isVisible())
panel.close(); c.close_all(); lab.close(); pump(0.2)
'''


def _ok(out: str) -> bool:
    return ("ppt_sent 1 win_visible False overlays 0 toast True" in out and "넣었습니다" in out
            and "html_table True" in out and "표 " in out and "행×" in out)


def test_FB_REAL_01_ppt_from_summary_and_table_copy_are_visibly_confirmed(tmp_path):
    from tests.conftest import run_on_desktop
    out = run_on_desktop(FLOW % (ROOT, tmp_path), _ok)
    assert _ok(out), out
