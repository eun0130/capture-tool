"""The company LLM (work edition): an OpenAI-compatible chat endpoint the company runs, set up in
설정 → AI (server address, model name, key). The key goes in a header, never in the URL or in
logs; nothing is sent until an address is set."""
from __future__ import annotations

import json
from typing import Callable

from .cloud_error import CloudError

TIMEOUT = 30
PATH = "/v1/chat/completions"

MESSAGES = {
    "config": "회사 AI 서버 주소가 없습니다. 설정 → AI에서 서버 주소와 모델 이름을 넣어 주세요.",
    "key": "회사 AI 키가 올바르지 않거나 권한이 없습니다. 설정 → AI에서 키를 확인해 주세요.",
    "quota": "회사 AI 사용 한도를 넘었습니다. 잠시 뒤 다시 해 주세요.",
    "network": "회사 AI 서버에 연결하지 못했습니다. 네트워크(사내망·VPN)를 확인해 주세요.",
    "server": "회사 AI 서버에 문제가 있습니다. 잠시 뒤 다시 해 주세요.",
    "blocked": "회사 AI가 이 내용은 처리하지 않았습니다(정책).",
    "model": "설정한 모델 이름을 회사 AI 서버가 모릅니다. 설정 → AI에서 모델 이름을 확인해 주세요.",
    "other": "회사 AI 요청이 실패했습니다.",
}


class CompanyLLMError(CloudError):
    MESSAGES = MESSAGES


def clean_endpoint(text: str) -> str:
    """The server address as typed, trimmed: no trailing '/', no trailing '/v1' (the client adds
    the path). Anything that isn't http(s) is refused ('')."""
    t = (text or "").strip().rstrip("/")
    if t.lower().endswith("/v1"):
        t = t[:-3].rstrip("/")
    if not (t.lower().startswith("https://") or t.lower().startswith("http://")) or len(t) <= 8:
        return ""
    return t


def _post(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class CompanyLLM:
    def __init__(self, key: str, endpoint: str, model: str, post: Callable | None = None, timeout: float = TIMEOUT):
        self._key = key or ""
        self.endpoint = clean_endpoint(endpoint)
        self.model = (model or "").strip()
        self._post = post or _post
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        if not self.endpoint:
            raise CompanyLLMError("config")
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.2}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"}
        try:
            status, data = self._post(self.endpoint + PATH, body, headers, self.timeout)
        except OSError as e:
            raise CompanyLLMError("network") from e
        return self._parse(status, data)

    @staticmethod
    def _parse(status: int, data: bytes) -> str:
        try:
            doc = json.loads(data or b"{}")
        except ValueError:
            doc = {}
        if not isinstance(doc, dict):
            doc = {}
        if status in (401, 403):
            raise CompanyLLMError("key")
        if status == 429:
            raise CompanyLLMError("quota")
        if status >= 500:
            raise CompanyLLMError("server")
        if status == 404:
            raise CompanyLLMError("model")
        if status == 400:
            raise CompanyLLMError("model" if "model" in json.dumps(doc).lower() else "other")
        if status != 200:
            raise CompanyLLMError("other")
        choices = doc.get("choices") or []
        first = choices[0] if choices and isinstance(choices[0], dict) else {}
        if first.get("finish_reason") == "content_filter":
            raise CompanyLLMError("blocked")
        content = (first.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise CompanyLLMError("other")
        return content.strip()

    def check(self) -> None:
        """Raises CompanyLLMError if the server, model or key doesn't work."""
        self.generate("Reply with the single word OK.")
