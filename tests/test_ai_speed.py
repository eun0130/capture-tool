"""Faster offline summary/translation without a cloud key: thread count, input de-duplication,
early stop when the model loops or echoes, bullet cap, and a cache for repeated requests."""
import pytest

from capture_tool.core import ai_local
from capture_tool.core.ai_local import LocalSummarizer, llm_threads
from capture_tool.core.ai_text import clean_summary, dedupe_text, summary_should_stop
from tests.test_ai_engines import FakeLLM, make_summarizer, make_translator, service


# --- threads ---------------------------------------------------------------------------------
def test_SPD_01_llm_uses_half_the_cores_at_most_8():
    assert llm_threads(2) == 1 and llm_threads(4) == 2 and llm_threads(8) == 4
    assert llm_threads(16) == 8 and llm_threads(32) == 8 and llm_threads(None) >= 1


def test_SPD_02_summarizer_default_threads_follow_cores():
    assert LocalSummarizer().threads == ai_local.LLM_THREADS


# --- input de-duplication ------------------------------------------------------------------------
def test_SPD_03_repeated_sentences_and_lines_are_dropped():
    s = "매출은 1,250억 원입니다. 매출은 1,250억 원입니다. 이익은 줄었습니다.\n\n매출은 1,250억 원입니다.\n새 줄."
    assert dedupe_text(s) == "매출은 1,250억 원입니다. 이익은 줄었습니다.\n\n새 줄."


def test_SPD_04_dedupe_keeps_short_repeats_numbers_and_layout():
    s = "예.\n예.\n표 1\n표 2\n\n\n끝"                     # short lines ("예.") are meaningful repeats
    assert dedupe_text(s) == s
    assert dedupe_text("") == "" and dedupe_text("   ") == ""


def test_SPD_05_dedupe_ignores_spacing_differences():
    assert dedupe_text("회의는  오후 2시에 시작합니다.\n회의는 오후 2시에 시작합니다.") == "회의는  오후 2시에 시작합니다."


# --- stop rules ------------------------------------------------------------------------------------
@pytest.mark.parametrize("out", [
    "<text>\n2026년 3분기 매출은",                                  # echoes the input
    "".join(f"• 요점 {i}\n" for i in range(8)) + "• ",              # starts a 9th bullet
    "• 매출 증가\n• 매출 증가\n• 매출 증가\n",                      # same line again and again
    "• 매출 •••••••••••••",                                       # one character in a loop
    "• 요약: " + "가나다라 " * 8,                                  # a short phrase looping
    "".join(f"- 항목 {i}: 값 {i * 7}\n" for i in range(13)),           # an outline far longer than a summary
])
def test_SPD_06_stop_when_model_loops_or_echoes(out):
    assert summary_should_stop(out)


@pytest.mark.parametrize("out", [
    "", "<think>\n\n</think>\n", "• 3분기 매출 1,250억 원(12% 증가)\n• 영업이익 96억 원(4% 감소)\n",
    "• 2026-10-15 14:00~18:00 점검\n• 문의: 김민수 대리(내선 2041)", "• 100, 200, 300, 400",
    "".join(f"• 요점 {i}\n" for i in range(6)),                       # 6 bullets is still fine
])
def test_SPD_07_normal_output_keeps_going(out):
    assert not summary_should_stop(out)


def test_SPD_08_clean_summary_caps_runaway_bullets_and_drops_echo_and_repeats():
    out = "<think>\n</think>\n• 가\n• 나\n• 나\n• 다\n• 라\n• 마\n• 바"
    assert clean_summary(out) == "• 가\n• 나\n• 다\n• 라\n• 마\n• 바"          # 6 kept: nothing lost
    many = "\n".join(f"• 요점 {i}" for i in range(12))
    assert clean_summary(many) == "\n".join(f"• 요점 {i}" for i in range(8))
    assert clean_summary("• 가\n<text>\n원문") == "• 가"
    assert clean_summary("• 가 ••••••••••") == "• 가"
    assert clean_summary("요약 문장입니다.") == "요약 문장입니다."
    assert clean_summary("• **영업 부문** – 80% 달성\n\n**") == "• 영업 부문 – 80% 달성"      # markdown is shown as plain text
    assert clean_summary("• 2 * 3 = 6") == "• 2 * 3 = 6"


# --- summarizer uses them ------------------------------------------------------------------------------
class LoopLLM(FakeLLM):
    """Writes a loop until told to stop; records how many steps it took."""

    def generate(self, prompt, max_new_tokens, on_text=None, cancel=None, stop=None):
        self.prompts.append(prompt)
        out = ""
        for i in range(max_new_tokens):
            out += "• 같은 말\n"
            if stop and stop(out):
                break
        self.steps = i + 1
        return out


def test_SPD_09_summarizer_stops_early_on_loop():
    llm = LoopLLM()
    s = LocalSummarizer(find=lambda: "d", loader=lambda d, t: llm)
    assert s.summarize("보고서 내용입니다.") == "• 같은 말"
    assert llm.steps < 10


def test_SPD_10_summarizer_gets_deduped_input():
    s, llm = make_summarizer()
    s.summarize("같은 문장이 반복됩니다. 같은 문장이 반복됩니다. 다른 문장입니다.")
    assert llm.prompts[0].count("같은 문장이 반복됩니다.") == 1


def test_SPD_11_echo_retries_once_with_instruction_after_text():
    class Echo(FakeLLM):
        def generate(self, prompt, max_new_tokens, on_text=None, cancel=None, stop=None):
            self.prompts.append(prompt)
            return "<text>\n원문" if len(self.prompts) == 1 else "• 요점"
    llm = Echo()
    s = LocalSummarizer(find=lambda: "d", loader=lambda d, t: llm)
    assert s.summarize("원문 내용입니다.") == "• 요점"
    assert len(llm.prompts) == 2 and llm.prompts[1].rstrip().endswith("요약하세요.")


# --- cache --------------------------------------------------------------------------------------------
def test_SPD_12_same_text_twice_is_answered_from_cache():
    summ, llm = make_summarizer()
    svc, _ = service(summarizer=summ)
    seen = []
    a = svc.summarize("반복 요청 글입니다.")
    b = svc.summarize("반복 요청 글입니다.", on_text=seen.append)
    assert a.text == b.text and len(llm.prompts) == 1 and seen == [b.text]
    svc.summarize("다른 글입니다.")
    assert len(llm.prompts) == 2


def test_SPD_13_cache_key_includes_language_and_engine_settings():
    summ, llm = make_summarizer()
    svc, _ = service(summarizer=summ)
    svc.summarize("같은 글.", "ko")
    svc.summarize("같은 글.", "en")
    assert len(llm.prompts) == 2
    t = make_translator()
    svc2, cloud = service(translator=t)
    r1 = svc2.translate("안녕하세요.", tgt="en")
    svc2.settings.ai_cloud_translate = True
    svc2.settings.ai_cloud_consent = True
    r2 = svc2.translate("안녕하세요.", tgt="en")
    assert r1.engine == "local" and r2.engine == "cloud"


def test_SPD_14_cache_is_bounded_and_failures_are_not_cached():
    from capture_tool.core import ai_service
    summ, llm = make_summarizer()
    svc, _ = service(summarizer=summ)
    for i in range(ai_service.CACHE_SIZE + 5):
        svc.summarize(f"글 {i}.")
    assert len(svc._cache) == ai_service.CACHE_SIZE
    calls = []

    class Fail(FakeLLM):
        def generate(self, *a, **k):
            calls.append(1)
            raise ai_local.Cancelled()
    svc2, _ = service(summarizer=LocalSummarizer(find=lambda: "d", loader=lambda d, t: Fail()))
    for _ in range(2):
        with pytest.raises(ai_local.Cancelled):
            svc2.summarize("취소될 글.")
    assert len(calls) == 2


def test_SPD_15_cloud_fallback_note_result_is_not_cached():
    """A result made offline only because the cloud failed should be retried next time."""
    from tests.test_ai_engines import FakeCloud
    from capture_tool.core.settings import Settings
    s = Settings(ai_cloud_translate=True, ai_cloud_consent=True)
    cloud = FakeCloud(fail="network")
    svc, _ = service(s, cloud=cloud)
    svc.translate("안녕하세요.", tgt="en")
    svc.translate("안녕하세요.", tgt="en")
    assert len(cloud.prompts) == 2


def test_SPD_16_random_text_never_breaks_the_new_helpers():
    import random
    rnd = random.Random(7)
    alphabet = "가나다 abc.!?。\n\n  •<>/text123ㅋ😀\t"
    for _ in range(3000):
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 300)))
        d = dedupe_text(s)
        assert dedupe_text(d) == d                     # applying twice changes nothing more
        assert len(d) <= len(s)
        summary_should_stop(s)
        c = clean_summary(s)
        assert "<text>" not in c and c.count("•") <= len(s)


# --- preload must not block a request ----------------------------------------------------------
def test_SPD_17_request_during_preload_waits_instead_of_busy():
    """Text mode preloads the 1.4 GB model; pressing 요약 meanwhile must wait for it, not fail
    with "번역·요약을 하는 중" (it left the result empty and the PPT button did nothing)."""
    import threading
    loading, release = threading.Event(), threading.Event()
    llm = FakeLLM()

    def slow_loader(d, t):
        loading.set()
        release.wait(5)
        return llm
    summ = LocalSummarizer(find=lambda: "d", loader=slow_loader)
    svc, _ = service(summarizer=summ)
    th = threading.Thread(target=svc.preload, args=("안녕하세요.",))
    th.start()
    assert loading.wait(2)
    assert not svc.busy                                   # preloading is not a user job
    out = {}
    job = threading.Thread(target=lambda: out.setdefault("r", svc.summarize("요약할 글입니다.")))
    job.start()
    release.set()
    job.join(5); th.join(5)
    assert out["r"].text == "• 요점 1"


def test_SPD_18_unload_and_second_preload_skip_while_preloading():
    import threading
    loading, release = threading.Event(), threading.Event()
    loads = []

    def slow_loader(d, t):
        loads.append(1)
        loading.set()
        release.wait(5)
        return FakeLLM()
    summ = LocalSummarizer(find=lambda: "d", loader=slow_loader)
    svc, _ = service(summarizer=summ)
    th = threading.Thread(target=svc.preload, args=("안녕하세요.",))
    th.start()
    assert loading.wait(2)
    svc.preload("또.")                                      # returns at once, no second load
    svc.unload()                                           # must not drop the model being loaded
    release.set(); th.join(5)
    assert len(loads) == 1 and summ._llm is not None
