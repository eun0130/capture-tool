"""Resource & safety guards: threads, memory, time budgets, log size, offline models."""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from capture_tool.core import ocr as ocr_mod
from capture_tool.core.shapes import MAX_COMPONENTS, detect
from tests import synth

ROOT = Path(__file__).resolve().parents[1]


def test_RES_01_blas_threads_limited_before_numpy_loads():
    """numpy's OpenBLAS spawns one thread per core and ~24 MB commit each (750 MB on 32 cores)."""
    code = ("import capture_tool, os, numpy; "
            "print(os.environ.get('OPENBLAS_NUM_THREADS'), os.environ.get('OMP_NUM_THREADS'))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert out == ["1", "1"]


def test_RES_02_ocr_engine_threads_capped():
    p = ocr_mod.ocr_params("korean")
    import os
    n = p["EngineConfig.onnxruntime.intra_op_num_threads"]
    assert 1 <= n <= 8 and n <= max(1, (os.cpu_count() or 2) // 2)     # half the cores at most
    assert p["EngineConfig.onnxruntime.inter_op_num_threads"] == 1
    assert p["Global.use_cls"] is False


def test_RES_03_dense_screen_detect_is_bounded():
    img = synth.canvas(1920, 1080)
    rng = np.random.default_rng(0)
    for _ in range(4000):                       # a very busy UI / web page
        x, y = int(rng.integers(0, 1900)), int(rng.integers(0, 1060))
        img[y:y + 14, x:x + 14] = (40, 40, 40)
    t = time.perf_counter()
    found = detect(img)
    assert time.perf_counter() - t < 4.0
    assert len(found) <= MAX_COMPONENTS


def test_RES_04_log_file_is_rotated(tmp_path):
    from capture_tool.app.main import setup_logging
    logger = setup_logging(tmp_path, max_bytes=20_000, backups=2)
    for i in range(3000):
        logger.info("line %05d %s", i, "x" * 40)
    for h in logger.handlers:
        h.flush()
    files = list(tmp_path.glob("capture.log*"))
    assert 1 < len(files) <= 3
    assert all(f.stat().st_size <= 25_000 for f in files)
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def test_SEC_01_missing_model_never_triggers_download(tmp_path, monkeypatch):
    """RapidOCR downloads absent models from the internet; the app promises to work offline."""
    monkeypatch.setattr(ocr_mod, "model_dir", lambda: tmp_path)
    called = []
    monkeypatch.setattr(ocr_mod, "_build_rapidocr", lambda params: called.append(params))
    eng = ocr_mod.OcrEngine(secondary_factory=lambda: None)
    with pytest.raises(ocr_mod.OcrUnavailable) as e:
        eng.recognize(np.zeros((50, 50, 3), np.uint8))
    assert called == []
    assert "korean_PP-OCRv5_rec_mobile.onnx" in str(e.value)


def test_SEC_02_bundled_models_present():
    missing = ocr_mod.missing_models(ocr_mod.REQUIRED_MODELS + ocr_mod.LATIN_MODELS)
    assert missing == []


def test_SEC_03_notifications_never_contain_recognized_text(qt_app, tmp_path):
    """Logged notices must not leak screen text (OCR output can hold personal data)."""
    from capture_tool.app.controller import Controller
    from capture_tool.core.ocr import OcrLine
    from capture_tool.core.settings import Settings
    from tests.test_app import FakeClipboard, FakeOcr, FakeScreen
    secret = "기밀문서 홍길동 010-9999-8888"
    c = Controller(FakeScreen(), FakeClipboard(), FakeOcr([OcrLine(secret, (0, 0, 100, 20), 0.99)]),
                   Settings(redact_pii=False), tmp_path / "s.json", tmp_path, sync=True)
    c.start_capture()
    ov = c.overlays[0]
    from capture_tool.core.geometry import Rect
    c.on_select_rect(Rect(10, 10, 200, 100), ov)
    c.on_toolbar_action("text")
    assert c.clipboard.last  # text was copied...
    assert not any("홍길동" in m or "9999" in m for m in c.messages)  # ...but never echoed/logged
    c.close_all()


def test_SEC_04_single_instance_only_accepts_capture_command():
    from capture_tool.app.main import handle_instance_message
    calls = []
    assert handle_instance_message(b"capture", calls.append) is True
    assert calls == ["capture"]
    for bad in (b"", b"capture\x00rm -rf", b"x" * 5000, b"open C:\\Windows"):
        assert handle_instance_message(bad, calls.append) is False
    assert calls == ["capture"]


@pytest.mark.windows
@pytest.mark.slow
def test_RES_05_real_process_footprint():
    """Whole app on the real desktop: memory, threads, and no growth after repeated captures."""
    script = r'''
import sys, os, tempfile, time, subprocess
sys.path.insert(0, r"%s")
import capture_tool
from PySide6.QtWidgets import QApplication
app = QApplication([])
from capture_tool.app.controller import Controller
from capture_tool.app.services import RealScreen
from capture_tool.core.geometry import Rect
from capture_tool.core.ocr import OcrEngine
from capture_tool.core.settings import Settings
from tests.test_app import FakeClipboard
def stat():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
        f"$p=Get-Process -Id {os.getpid()}; \"$($p.WorkingSet64) $($p.PrivateMemorySize64) $($p.Threads.Count)\""],
        capture_output=True, text=True).stdout.split()
    return int(out[0]) >> 20, int(out[1]) >> 20, int(out[2])
tmp = tempfile.mkdtemp()
eng = OcrEngine(); eng._load(); eng._load_secondary()
c = Controller(RealScreen(), FakeClipboard(), eng, Settings(), tmp + "/s.json", tmp, sync=True)
c.prewarm()
def one():
    c.start_capture(); app.processEvents()
    ov = c.overlays[0]; m = ov.monitor
    c.on_select_rect(Rect(m.rect.x + 50, m.rect.y + 50, 900, 500), ov)
    c.finish("copy"); app.processEvents()
    c.clipboard.payloads.clear()   # the fake clipboard would otherwise keep every copy
one(); one()                        # first captures allocate one-time buffers
time.sleep(1); app.processEvents()
ws0, pv0, th0 = stat()
for i in range(8):
    one()
time.sleep(1); app.processEvents()
ws1, pv1, th1 = stat()
print(f"RESULT ws0={ws0} pv0={pv0} th0={th0} ws1={ws1} pv1={pv1} th1={th1}")
''' % ROOT
    from tests.conftest import run_on_desktop

    def values(out):
        line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
        return line, ({k: int(x) for k, x in (kv.split("=") for kv in line.split()[1:])} if line else None)

    def ok(out):
        _, v = values(out)
        return bool(v) and v["pv0"] < 450 and v["th0"] < 60 and v["ws1"] - v["ws0"] < 40 \
            and v["pv1"] - v["pv0"] < 40 and v["th1"] - v["th0"] < 5

    out = run_on_desktop(script, ok, timeout=300)
    line, _ = values(out)
    assert line, out
    v = dict(kv.split("=") for kv in line.split()[1:])
    v = {k: int(x) for k, x in v.items()}
    print(line)
    assert v["pv0"] < 450, line          # was ~1012 MB
    assert v["th0"] < 60, line           # was 128 threads on a 32-core PC
    assert v["ws1"] - v["ws0"] < 40, line   # 8 more captures must not pile up (steady state)
    assert v["pv1"] - v["pv0"] < 40, line
    assert v["th1"] - v["th0"] < 5, line
