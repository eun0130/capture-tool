"""Translation / summary requests: pick the engine from the settings, ask for consent before the
first cloud use, mask personal data before anything leaves the PC, fall back to offline when
the cloud fails, and run one job at a time."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from .ai_local import Busy
from .ai_text import default_target, detect_lang, summary_prompt, translate_prompt
from .gemini import GeminiError
from .redact import mask

MAX_INPUT = 20000


@dataclass
class AiResult:
    text: str
    engine: str                  # "local" or "cloud"
    src: str | None = None
    tgt: str | None = None
    note: str = ""


class ConsentNeeded(Exception):
    """The cloud is selected but the person hasn't agreed to send text to Google yet."""


_FALLBACK = {
    "quota": "Gemini 무료 한도를 다 써서 오프라인으로 처리했습니다.",
    "key": "Gemini 키가 올바르지 않아 오프라인으로 처리했습니다. 설정 → AI에서 키를 확인해 주세요.",
    "network": "Gemini에 연결되지 않아 오프라인으로 처리했습니다.",
}


class AiService:
    def __init__(self, settings, translator, summarizer, cloud_factory: Callable | None = None,
                 get_key: Callable[[], str | None] | None = None):
        self.settings = settings
        self.translator, self.summarizer = translator, summarizer
        self.cloud_factory = cloud_factory
        self.get_key = get_key or (lambda: None)
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @contextmanager
    def _job(self):
        if not self._lock.acquire(blocking=False):
            raise Busy("번역·요약을 하는 중입니다. 끝나면 다시 해 주세요.")
        try:
            yield
        finally:
            self._lock.release()

    @staticmethod
    def _cap(text: str) -> tuple[str, str]:
        if len(text) > MAX_INPUT:
            return text[:MAX_INPUT], f"글이 길어 앞부분 {MAX_INPUT:,}자만 처리했습니다."
        return text, ""

    def _cloud(self):
        key = self.get_key()
        if not key or self.cloud_factory is None:
            return None, "Gemini 키가 설정되지 않아 오프라인으로 처리했습니다. (설정 → AI에서 키를 넣을 수 있습니다)"
        if not self.settings.ai_cloud_consent:
            raise ConsentNeeded()
        return self.cloud_factory(key), ""

    @staticmethod
    def _join(*notes: str) -> str:
        return " ".join(n for n in notes if n)

    def translate(self, text: str, src: str | None = None, tgt: str | None = None, cancel=None) -> AiResult:
        with self._job():
            text, note = self._cap(text)
            src = src or detect_lang(text)
            tgt = tgt or self.settings.ai_target_lang or default_target(src)
            if self.settings.ai_cloud_translate:
                cloud, why = self._cloud()
                if cloud is not None:
                    try:
                        out = cloud.generate(translate_prompt(mask(text), src, tgt))
                        return AiResult(out, "cloud", src, tgt, note)
                    except GeminiError as e:
                        why = _FALLBACK.get(e.kind, str(e) + " 오프라인으로 처리했습니다.")
                note = self._join(note, why)
            out = self.translator.translate(text, src, tgt, cancel=cancel)
            return AiResult(out, "local", src, tgt, note)

    def summarize(self, text: str, lang: str = "ko", on_text=None, cancel=None) -> AiResult:
        with self._job():
            text, note = self._cap(text)
            if self.settings.ai_summary_engine == "cloud":
                cloud, why = self._cloud()
                if cloud is not None:
                    try:
                        return AiResult(cloud.generate(summary_prompt(mask(text), lang)), "cloud", tgt=lang, note=note)
                    except GeminiError as e:
                        why = _FALLBACK.get(e.kind, str(e) + " 오프라인으로 처리했습니다.")
                note = self._join(note, why)
            out = self.summarizer.summarize(text, lang, on_text=on_text, cancel=cancel)
            return AiResult(out, "local", tgt=lang, note=note)

    def preload(self, text: str) -> None:
        """Load the models the next translate / summary of `text` would need, ahead of time
        (call in the background). Skipped while a job runs; missing models are left alone."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            src = detect_lang(text)
            tgt = self.settings.ai_target_lang or default_target(src)
            if not self.settings.ai_cloud_translate and not self.translator.missing(src, tgt):
                from .ai_text import route
                for a, b in route(src, tgt):
                    self.translator._get(f"{a}_{b}")
            if self.settings.ai_summary_engine == "local" and self.summarizer.available():
                self.summarizer._get()
        finally:
            self._lock.release()

    def unload(self) -> None:
        """Free model memory (called after the AI has been idle for a while)."""
        if not self.busy:
            self.translator.unload()
            self.summarizer.unload()
