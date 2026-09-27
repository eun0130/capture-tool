"""OCR must start even when creating a network socket hangs (seen on a PC with online-banking
security software: `socket.socket(AF_INET6)` never returned, and urllib3 — imported by
rapidocr for model downloads this app never does — probes IPv6 that way at import)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import socket, sys, time
sys.path.insert(0, r"%s")
_real = socket.socket
class Hanging(_real):
    def __init__(self, family=-1, *a, **k):
        if family == socket.AF_INET6:
            time.sleep(3600)                      # the network filter never answers
        super().__init__(family, *a, **k)
socket.socket = Hanging
from capture_tool.core import ocr
ocr.ocr_params("korean")
ocr._rapidocr()                                   # imports rapidocr.RapidOCR (and with it urllib3)
print("IMPORTED", socket.has_ipv6)
'''


def test_OCRI_01_rapidocr_import_does_not_touch_the_network(tmp_path):
    r = subprocess.run([sys.executable, "-c", SCRIPT % ROOT], capture_output=True, text=True, timeout=120)
    assert "IMPORTED" in r.stdout, r.stdout + r.stderr
    assert "IMPORTED True" in r.stdout            # the flag is put back afterwards
