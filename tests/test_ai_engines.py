"""Offline translator/summarizer (fake models), Gemini client (fake HTTP), key storage, and the
service that picks the engine, masks personal data and falls back."""
import json
import sys
import threading

import pytest

from capture_tool.core import ai_local, gemini
from capture_tool.core.ai_local import LocalSummarizer, LocalTranslator, ModelMissing, strip_think
from capture_tool.core.ai_service import AiService, ConsentNeeded
from capture_tool.core.settings import Settings


# --- offline translation --------------------------------------------------------------------
class FakeMT:
    """Stands in for one CTranslate2 pair: tags each piece with the pair."""
    loads = 0

    def __init__(self, pair):
        FakeMT.loads += 1
        self.pair = pair
        self.batches = []

    def translate_batch(self, pieces):
        self.batches.append(list(pieces))
        return [f"[{self.pair}]{p}" for p in pieces]


def make_translator(installed=("ko_en", "en_ko", "ja_en", "en_ja")):
    return LocalTranslator(find=lambda pair: pair if pair in installed else None,
                           loader=lambda d: FakeMT(d))


def test_AIE_01_direct_pair_keeps_layout():
    t = make_translator()
    out = t.translate("첫 문장. 둘째 문장.\n\n셋째", "ko", "en")
    assert out == "[ko_en]첫 문장. [ko_en]둘째 문장.\n\n[ko_en]셋째"


def test_AIE_02_pivot_through_english():
    out = make_translator().translate("こんにちは", "ja", "ko")
    assert out == "[en_ko][ja_en]こんにちは"


def test_AIE_03_missing_packs_are_named():
    t = make_translator(installed=("ko_en",))
    assert t.missing("fr", "ko") == ["mt-fr_en", "mt-en_ko"]
    with pytest.raises(ModelMissing) as e:
        t.translate("Bonjour", "fr", "ko")
    assert e.value.packs == ["mt-fr_en", "mt-en_ko"]


def test_AIE_04_same_language_and_empty():
    t = make_translator()
    assert t.translate("그대로", "ko", "ko") == "그대로"
    assert t.translate("", "ko", "en") == ""


def test_AIE_05_models_load_once_and_unload():
    FakeMT.loads = 0
    t = make_translator()
    t.translate("a.", "ko", "en")
    t.translate("b.", "ko", "en")
    assert FakeMT.loads == 1
    t.unload()
    t.translate("c.", "ko", "en")
    assert FakeMT.loads == 2


def test_AIE_06_cancel_between_batches():
    t = make_translator()
    with pytest.raises(ai_local.Cancelled):
        t.translate("가. " * 200, "ko", "en", cancel=lambda: True)


def test_AIE_07_big_input_goes_in_batches():
    t = make_translator()
    t.translate("\n".join(f"문장 {i}." for i in range(100)), "ko", "en")
    mt = t._loaded["ko_en"]
    assert len(mt.batches) > 1 and max(len(b) for b in mt.batches) <= ai_local.BATCH


# --- offline summary --------------------------------------------------------------------------
class FakeLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, max_new_tokens, on_text=None, cancel=None):
        self.prompts.append(prompt)
        out = "<think>\n\n</think>\n• 요점 " + str(len(self.prompts))
        if on_text:
            on_text(out)
        return out


def make_summarizer(installed=True):
    llm = FakeLLM()
    s = LocalSummarizer(find=lambda: "dir" if installed else None, loader=lambda d, threads: llm)
    return s, llm


def test_AIE_08_short_text_one_call_think_removed():
    s, llm = make_summarizer()
    assert s.summarize("짧은 보고서 내용입니다.", "ko") == "• 요점 1"
    assert len(llm.prompts) == 1 and "짧은 보고서" in llm.prompts[0]


def test_AIE_09_long_text_is_summarized_in_parts_then_combined():
    s, llm = make_summarizer()
    long = "\n\n".join("문단 " + "내용 " * 400 for _ in range(4))
    out = s.summarize(long, "ko")
    assert len(llm.prompts) >= 3 and out.startswith("•")
    assert "요점 1" in llm.prompts[-1]                 # the final pass sees the part summaries


def test_AIE_10_summary_model_missing():
    s, _ = make_summarizer(installed=False)
    with pytest.raises(ModelMissing) as e:
        s.summarize("글", "ko")
    assert e.value.packs == ["llm-qwen3-1.7b"]


def test_AIE_11_strip_think():
    assert strip_think("<think>생각</think>\n답") == "답"
    assert strip_think("<think>끝나지 않은 생각") == ""
    assert strip_think("그냥 답") == "그냥 답"


# --- Gemini -----------------------------------------------------------------------------------------
KEY = "AIza" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"


class FakePost:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, json.loads(body), headers))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def ok(text):
    return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()


def test_AIE_12_gemini_call_shape_and_key_in_header_not_url():
    post = FakePost(ok("안녕"))
    g = gemini.Gemini(KEY, post=post)
    assert g.generate("hi") == "안녕"
    url, body, headers = post.calls[0]
    assert KEY not in url and headers["x-goog-api-key"] == KEY
    assert body["contents"][0]["parts"][0]["text"] == "hi"
    assert url.startswith("https://generativelanguage.googleapis.com/")


def test_AIE_13_gemini_errors_are_classified():
    cases = [((400, b'{"error":{"status":"INVALID_ARGUMENT","message":"API key not valid"}}'), "key"),
             ((403, b'{"error":{"status":"PERMISSION_DENIED"}}'), "key"),
             ((429, b'{"error":{"status":"RESOURCE_EXHAUSTED"}}'), "quota"),
             ((500, b"{}"), "server"),
             (OSError("timed out"), "network"),
             ((200, b'{"promptFeedback":{"blockReason":"SAFETY"}}'), "blocked")]
    for reply, kind in cases:
        with pytest.raises(gemini.GeminiError) as e:
            gemini.Gemini(KEY, post=FakePost(reply)).generate("x")
        assert e.value.kind == kind and KEY not in str(e.value)


def test_AIE_14_gemini_retired_model_falls_back_to_next():
    post = FakePost((404, b'{"error":{"status":"NOT_FOUND"}}'), ok("다음 모델"))
    assert gemini.Gemini(KEY, post=post).generate("x") == "다음 모델"
    assert post.calls[0][0] != post.calls[1][0]


def test_AIE_15_find_key_in_clipboard_text():
    assert gemini.find_key(f"복사한 키: {KEY}  ") == KEY
    assert gemini.find_key("AIza-too-short") is None
    assert gemini.find_key("") is None


# --- key storage (Windows DPAPI) --------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_AIE_16_key_is_encrypted_for_this_windows_user():
    from capture_tool.platform import secret
    blob = secret.protect(KEY)
    assert KEY not in blob and secret.unprotect(blob) == KEY
    with pytest.raises(secret.SecretError):
        secret.unprotect("bm90IGEgYmxvYg==")


# --- service: which engine, consent, masking, fallback -----------------------------------------------------
class FakeCloud:
    def __init__(self, fail=None):
        self.prompts, self.fail = [], fail

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise gemini.GeminiError(self.fail, "실패")
        return "클라우드 결과"


def service(settings=None, key=KEY, cloud=None, translator=None, summarizer=None):
    s = settings or Settings()
    cloud = cloud or FakeCloud()
    svc = AiService(s, translator or make_translator(), summarizer or make_summarizer()[0],
                    cloud_factory=lambda k: cloud, get_key=lambda: key)
    return svc, cloud


def test_AIE_17_default_is_offline_for_both():
    svc, cloud = service()
    r = svc.translate("안녕하세요.")
    assert (r.src, r.tgt, r.engine) == ("ko", "en", "local") and r.text.startswith("[ko_en]")
    assert svc.summarize("보고서.").engine == "local"
    assert cloud.prompts == []


def test_AIE_18_cloud_needs_consent_once():
    s = Settings(ai_summary_engine="cloud")
    svc, cloud = service(s)
    with pytest.raises(ConsentNeeded):
        svc.summarize("보고서.")
    s.ai_cloud_consent = True
    r = svc.summarize("보고서.")
    assert r.engine == "cloud" and r.text == "클라우드 결과"


def test_AIE_19_personal_data_masked_before_cloud():
    s = Settings(ai_summary_engine="cloud", ai_cloud_translate=True, ai_cloud_consent=True, redact_pii=True)
    svc, cloud = service(s)
    svc.summarize("담당 010-1234-5678, kim@example.com 에게 연락")
    svc.translate("담당 010-1234-5678")
    assert all("010-1234-5678" not in p and "kim@example.com" not in p for p in cloud.prompts)


def test_AIE_20_cloud_failure_falls_back_to_offline_with_note():
    s = Settings(ai_summary_engine="cloud", ai_cloud_translate=True, ai_cloud_consent=True)
    svc, _ = service(s, cloud=FakeCloud(fail="quota"))
    r = svc.summarize("보고서.")
    assert r.engine == "local" and "한도" in r.note
    r = svc.translate("안녕.")
    assert r.engine == "local" and r.note


def test_AIE_21_bad_key_is_reported_not_hidden():
    s = Settings(ai_summary_engine="cloud", ai_cloud_consent=True)
    svc, _ = service(s, cloud=FakeCloud(fail="key"))
    r = svc.summarize("보고서.")
    assert r.engine == "local" and "키" in r.note


def test_AIE_22_cloud_selected_but_no_key_uses_offline():
    s = Settings(ai_summary_engine="cloud", ai_cloud_consent=True)
    svc, cloud = service(s, key=None)
    r = svc.summarize("보고서.")
    assert r.engine == "local" and "키" in r.note and cloud.prompts == []


def test_AIE_23_explicit_languages_and_huge_input_cut():
    svc, _ = service()
    r = svc.translate("hello.", src="en", tgt="ja")
    assert (r.src, r.tgt) == ("en", "ja")
    r = svc.summarize("가. " * 20000)
    assert "앞부분" in r.note


def test_AIE_24_one_job_at_a_time():
    started, release = threading.Event(), threading.Event()

    class Slow(FakeLLM):
        def generate(self, *a, **k):
            started.set()
            release.wait(5)
            return "• 끝"
    summ = LocalSummarizer(find=lambda: "d", loader=lambda d, t: Slow())
    svc, _ = service(summarizer=summ)
    th = threading.Thread(target=lambda: svc.summarize("글."))
    th.start()
    started.wait(2)
    assert svc.busy
    with pytest.raises(ai_local.Busy):
        svc.summarize("또.")
    release.set()
    th.join(5)
    assert not svc.busy


def test_AIE_25_preload_loads_the_translation_pair_and_local_summary_only():
    FakeMT.loads = 0
    summ, llm = make_summarizer()
    svc, _ = service(summarizer=summ)
    svc.preload("Quarterly revenue grew.")
    assert FakeMT.loads == 1 and summ._llm is llm               # en->ko pair and the summary model
    s = Settings(ai_summary_engine="cloud")
    summ2, _ = make_summarizer()
    svc2, _ = service(s, summarizer=summ2)
    svc2.preload("안녕하세요.")
    assert summ2._llm is None                                    # cloud summary: no 1.4 GB load


def test_AIE_26_preload_skips_missing_models_and_busy_service():
    t = make_translator(installed=())
    summ, _ = make_summarizer(installed=False)
    svc, _ = service(translator=t, summarizer=summ)
    svc.preload("글")                                            # nothing installed: no error
    svc._lock.acquire()
    try:
        svc.preload("Hello.")                                    # busy: skipped, no deadlock
    finally:
        svc._lock.release()
