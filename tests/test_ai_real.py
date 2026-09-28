"""Real offline models (skipped when the packs aren't on this PC): translation in every
direction, summary quality/speed/memory, unloading. Gemini only with GEMINI_API_KEY set."""
import ctypes
import os
import sys
import time
from ctypes import wintypes

import pytest

from capture_tool.core import model_store as ms
from capture_tool.core.ai_local import LocalSummarizer, LocalTranslator

pytestmark = [pytest.mark.slow, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]


def have(*packs):
    return all(ms.installed_dir(ms.CATALOG[p]) for p in packs)


def rss_mb() -> int:
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                   [(n, ctypes.c_size_t) for n in ("Peak", "WorkingSetSize", "QPPP", "QPP", "QNPPP", "QNPP",
                                                   "PagefileUsage", "PeakPagefileUsage")]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.PagefileUsage // 2**20


@pytest.mark.skipif(not have("mt-ko_en", "mt-en_ko"), reason="ko<->en packs not installed")
def test_AIR_01_korean_english_both_ways():
    t = LocalTranslator()
    t0 = time.perf_counter()
    en = t.translate("3분기 매출은 1,250억 원으로 12% 증가했습니다.\n납기는 10월 15일입니다.", "ko", "en")
    ko = t.translate("Please submit the report by Friday.", "en", "ko")
    assert time.perf_counter() - t0 < 10
    assert "12" in en and "October" in en and "15" in en and en.count("\n") == 1
    assert "금요일" in ko and "보고서" in ko


@pytest.mark.skipif(not have("mt-ja_en", "mt-en_ko", "mt-fr_en", "mt-zh_en", "mt-es_en", "mt-de_en"),
                    reason="packs not installed")
@pytest.mark.parametrize("src,text,expect", [
    ("ja", "会議は明日の午後3時に始まります。", "회의"),
    ("fr", "La réunion commence demain à 15 heures.", "회의"),
    ("zh", "会议明天下午三点开始。", "회의"),
    ("es", "La reunión empieza mañana a las tres.", "회의"),
    ("de", "Die Besprechung beginnt morgen um 15 Uhr.", "회의"),
])
def test_AIR_02_other_languages_to_korean_via_english(src, text, expect):
    out = LocalTranslator().translate(text, src, "ko")
    assert expect in out or "미팅" in out, out


@pytest.mark.skipif(not have("llm-qwen3-1.7b"), reason="summary model not installed")
def test_AIR_03_summary_quality_speed_memory_and_unload():
    text = ("2026년 3분기 영업 보고\n3분기 매출은 1,250억 원으로 전년 동기 대비 12% 증가했습니다. "
            "해외 매출 비중은 38%로 처음으로 30%를 넘었습니다.\n영업이익은 원자재 가격 상승 영향으로 4% 감소한 "
            "96억 원을 기록했습니다.\n4분기에는 신제품 2종 출시와 동남아 유통망 확대를 계획하고 있으며, 연간 매출 "
            "목표는 4,800억 원입니다.\n다만 환율 변동과 물류비 상승은 계속 위험 요인으로 관리가 필요합니다.")
    before = rss_mb()
    s = LocalSummarizer()
    seen = []
    t0 = time.perf_counter()
    out = s.summarize(text, "ko", on_text=seen.append)
    took = time.perf_counter() - t0
    peak = rss_mb()
    assert "<think>" not in out and out.count("•") >= 2, out
    assert "1,250" in out and "12%" in out
    assert took < 60, took
    assert seen                                           # streamed while generating
    assert peak - before < 3500, peak - before            # model memory stays bounded
    s.unload()
    import gc
    gc.collect()
    assert rss_mb() < peak - 500                          # memory is given back


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="no GEMINI_API_KEY")
def test_AIR_04_gemini_real_call():
    from capture_tool.core.gemini import Gemini
    out = Gemini(os.environ["GEMINI_API_KEY"]).generate("Reply with the single word OK.")
    assert "OK" in out.upper()
