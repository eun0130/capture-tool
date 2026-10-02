"""Measure every user-facing action on this PC (real screen, clipboard, OCR, PowerPoint).

  python tools/bench.py            -> table on stdout, JSON in bench-results.json
PowerPoint actions use a brand-new presentation that is closed unsaved afterwards."""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from capture_tool.app.controller import Controller  # noqa: E402
from capture_tool.app.services import RealClipboard, RealScreen  # noqa: E402
from capture_tool.core.ocr import OcrEngine  # noqa: E402
from capture_tool.core.settings import Settings  # noqa: E402
from tests.tallocr import tall_page  # noqa: E402
from tests.test_app import drag  # noqa: E402

RESULTS: dict[str, dict] = {}


def pump(sec: float = 0.0) -> None:
    end = time.perf_counter() + sec
    app.processEvents()
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def measure(name: str, fn, runs: int = 5, setup=None, teardown=None) -> None:
    times = []
    for _ in range(runs):
        ctx = setup() if setup else None
        t = time.perf_counter()
        fn(ctx)
        times.append((time.perf_counter() - t) * 1000)
        if teardown:
            teardown(ctx)
    RESULTS[name] = {"median_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1), "runs": runs}
    print(f"{name:<38} median {statistics.median(times):8.1f} ms   max {max(times):8.1f} ms", flush=True)


def controller(**kw) -> Controller:
    tmp = tempfile.mkdtemp()
    eng = OCR
    return Controller(RealScreen(), RealClipboard(), eng, Settings(save_dir=tmp, **kw), tmp + "/s.json", tmp, sync=True)


def selected(c: Controller, w=900, h=600):
    c.start_capture()
    pump(0.05)
    ov = c.active_overlay or c.overlays[0]
    drag(ov, (100, 100), (100 + w, 100 + h))
    return ov


def main(selected_only: list[str] | None = None) -> None:
    global OCR
    OCR = OcrEngine()
    OCR._load()
    OCR._load_secondary()
    c = controller()

    def start(_):
        c.start_capture()

    def stop(_):
        c.cancel()
        pump(0.05)
    measure("캡처 시작 (화면 정지)", start, teardown=stop)

    measure("복사 (Enter, 900x600)", lambda ov: c.finish("copy"), setup=lambda: selected(c))
    measure("저장 (Ctrl+S)", lambda ov: c.finish("save"), setup=lambda: selected(c))
    measure("고정 (F3)", lambda ov: c.finish("pin"), setup=lambda: selected(c), teardown=lambda _: c.close_pins())

    from tests.render import render_text
    fixed = render_text([f"{i}번 항목 견적 요약 금액 {1000 * i:,}원 담당 홍길동 Quarterly revenue grew"
                         for i in range(14)], width=900, size=20)
    measure("텍스트 인식 (900x600 고정 그림, 14줄)", lambda _: OCR.recognize(fixed), runs=5)
    page, _ = tall_page(height=6000, width=1200)
    measure("텍스트 인식 (1200x6000 긴 그림)", lambda _: OCR.recognize(page), runs=2)

    from capture_tool.core.shapes import detect
    shot = selected(c)
    raw = shot.crop(c.session.selection)
    c.cancel()
    measure("도형 인식 (900x600)", lambda _: detect(raw), runs=3)

    from capture_tool.core.stitch import Stitcher
    from tests.scrollsim import FakePage, make_page
    fp = FakePage(make_page(8000, w=1300), vh=1000, px_per_notch=100)
    frames = []
    for _ in range(12):
        frames.append(fp.frame())
        fp.wheel(-6)

    def stitch(_):
        st = Stitcher()
        for f in frames:
            st.add(f)
    measure("스크롤 이어붙이기 (12장 1300x1000)", stitch, runs=3)

    big = make_page(8000, w=1300)
    measure("편집 창 열기 (1300x8000)", lambda _: c.open_editor(big, 96, "bench"), runs=3, teardown=stop)

    try:
        from capture_tool.platform import powerpoint
        if powerpoint.installed():
            from capture_tool.platform.powerpoint import Picture, TextItem

            def closer(pres, slide, added):
                pres.Saved = True
                pres.Close()
            img = np.full((600, 900, 3), 200, np.uint8)
            measure("PPT로 (그림, 새 문서)", lambda _: powerpoint.send(Picture(img), new_presentation=True,
                                                                 hook=closer, timeout=30), runs=3)
            measure("PPT로 (글자)", lambda _: powerpoint.send(TextItem("견적 요약\n담당 홍길동"), new_presentation=True,
                                                          hook=closer, timeout=30), runs=3)
    except Exception as e:  # noqa: BLE001
        print("PowerPoint skipped:", e)

    try:
        from capture_tool.core.ai_local import LocalSummarizer, LocalTranslator
        tr = LocalTranslator()
        measure("번역 첫 실행 (모델 불러오기 포함)", lambda _: tr.translate("회의는 내일 오후 3시에 시작합니다.", "ko", "en"),
                runs=1)
        measure("번역 (모델 불러온 뒤, 5문장)", lambda _: tr.translate(
            "회의는 내일 시작합니다. 자료를 준비해 주세요. 매출은 12% 늘었습니다. 일정은 바뀔 수 있습니다. 감사합니다.",
            "ko", "en"), runs=3)
        sm = LocalSummarizer()
        if sm.available():
            text = "3분기 매출은 1,250억 원으로 12% 늘었다. 영업이익은 4% 줄었다. 4분기에는 신제품 2종을 낸다."
            measure("요약 첫 실행 (모델 불러오기 포함)", lambda _: sm.summarize(text), runs=1)
            measure("요약 (모델 불러온 뒤)", lambda _: sm.summarize(text), runs=2)
    except Exception as e:  # noqa: BLE001
        print("AI skipped:", e)

    c.close_all()
    out = ROOT / "bench-results.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
