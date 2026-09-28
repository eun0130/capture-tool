"""Google Gemini API (free tier with the user's own key). The key goes in a header, never in the
URL or in logs. Errors are sorted into kinds the UI can explain."""
from __future__ import annotations

import json
import re
from typing import Callable

BASE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-flash-lite-latest"]
KEY_PAGE = "https://aistudio.google.com/apikey"
KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{35}")
TIMEOUT = 30

MESSAGES = {
    "key": "Gemini 키가 올바르지 않거나 사용할 수 없습니다. 설정 → AI에서 키를 다시 넣어 주세요.",
    "quota": "Gemini 무료 사용 한도를 다 썼습니다. 잠시 뒤(또는 내일) 다시 쓸 수 있습니다.",
    "network": "Gemini에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.",
    "server": "Gemini 서버에 문제가 있습니다. 잠시 뒤 다시 해 주세요.",
    "blocked": "Gemini가 이 내용은 처리하지 않았습니다(안전 정책).",
    "model": "사용할 수 있는 Gemini 모델을 찾지 못했습니다. 캡처 도구를 업데이트해 주세요.",
    "other": "Gemini 요청이 실패했습니다.",
}


class GeminiError(Exception):
    def __init__(self, kind: str, message: str | None = None):
        super().__init__(message or MESSAGES.get(kind, MESSAGES["other"]))
        self.kind = kind


def find_key(text: str) -> str | None:
    m = KEY_RE.search(text or "")
    return m.group(0) if m else None


def _post(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Gemini:
    def __init__(self, key: str, post: Callable | None = None, timeout: float = TIMEOUT):
        self._key = key
        self._post = post or _post
        self.timeout = timeout
        self._model = 0

    def generate(self, prompt: str) -> str:
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"temperature": 0.2}}).encode("utf-8")
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        for i in range(self._model, len(MODELS)):
            try:
                status, data = self._post(BASE.format(MODELS[i]), body, headers, self.timeout)
            except OSError as e:
                raise GeminiError("network") from e
            if status == 404:
                continue                       # model retired: try the next one
            self._model = i
            return self._parse(status, data)
        raise GeminiError("model")

    @staticmethod
    def _parse(status: int, data: bytes) -> str:
        try:
            doc = json.loads(data or b"{}")
        except ValueError:
            doc = {}
        if status in (401, 403):
            raise GeminiError("key")
        if status == 400:
            text = json.dumps(doc)
            raise GeminiError("key" if "API key" in text or "API_KEY" in text else "other")
        if status == 429:
            raise GeminiError("quota")
        if status >= 500:
            raise GeminiError("server")
        if status != 200:
            raise GeminiError("other")
        cands = doc.get("candidates") or []
        parts = (cands[0].get("content") or {}).get("parts") if cands else None
        if not parts:
            raise GeminiError("blocked" if doc.get("promptFeedback", {}).get("blockReason") or cands else "other")
        return "".join(p.get("text", "") for p in parts).strip()

    def check(self) -> None:
        """Raises GeminiError if the key doesn't work."""
        self.generate("Reply with the single word OK.")
