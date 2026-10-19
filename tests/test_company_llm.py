"""The work edition's cloud engine: an OpenAI-compatible company LLM server. `post` is injected,
so nothing here touches the network."""
import json

import pytest

from capture_tool.core.cloud_error import CloudError
from capture_tool.core.company_llm import CompanyLLM, CompanyLLMError, MESSAGES, clean_endpoint

KEY = "sk-company-SECRET-0123456789"


def answer(text: str, finish: str = "stop") -> bytes:
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]}).encode()


def recorder(status: int = 200, data: bytes = b"", raise_=None):
    calls = []

    def post(url, body, headers, timeout):
        calls.append((url, body, headers, timeout))
        if raise_ is not None:
            raise raise_
        return status, data
    return calls, post


def test_CL_01_request_goes_to_chat_completions_with_a_bearer_key():
    calls, post = recorder(data=answer("  안녕하세요 요약입니다 \n"))
    llm = CompanyLLM(KEY, "https://llm.corp.local", "corp-chat", post=post, timeout=7)
    assert llm.generate("요약해 줘") == "안녕하세요 요약입니다"
    url, body, headers, timeout = calls[0]
    assert url == "https://llm.corp.local/v1/chat/completions" and timeout == 7
    assert headers["Authorization"] == f"Bearer {KEY}" and headers["Content-Type"] == "application/json"
    doc = json.loads(body)
    assert doc == {"model": "corp-chat", "messages": [{"role": "user", "content": "요약해 줘"}], "temperature": 0.2}
    assert KEY not in url


def test_CL_02_endpoint_is_cleaned_and_must_be_http():
    assert clean_endpoint(" https://llm.corp.local/ ") == "https://llm.corp.local"
    assert clean_endpoint("http://10.0.0.5:8000/v1/") == "http://10.0.0.5:8000"      # /v1 is added by the client
    assert clean_endpoint("https://x.y/v1") == "https://x.y"
    assert clean_endpoint("llm.corp.local") == "" and clean_endpoint("") == "" and clean_endpoint("ftp://a") == ""
    calls, post = recorder(data=answer("ok"))
    for bad in ("", "llm.corp.local"):
        with pytest.raises(CompanyLLMError) as e:
            CompanyLLM(KEY, bad, "m", post=post).generate("x")
        assert e.value.kind == "config" and "설정" in str(e.value)
    assert calls == []                                       # never sent anywhere
    assert CompanyLLM(KEY, "https://x.y/v1/", "m", post=post).generate("x") == "ok"
    assert calls[0][0] == "https://x.y/v1/chat/completions"


@pytest.mark.parametrize("status,data,kind", [
    (401, b"{}", "key"), (403, b"{}", "key"), (429, b"{}", "quota"),
    (500, b"", "server"), (502, b"", "server"), (503, b"", "server"),
    (404, b'{"error": {"message": "model not found"}}', "model"),
    (400, b'{"error": {"message": "The model `x` does not exist"}}', "model"),
    (400, b'{"error": {"message": "bad request"}}', "other"),
    (200, b'{"choices": []}', "other"), (200, b"not json", "other"),
    (200, answer("", "content_filter"), "blocked"),
])
def test_CL_03_errors_are_sorted_into_kinds(status, data, kind):
    _, post = recorder(status=status, data=data)
    with pytest.raises(CompanyLLMError) as e:
        CompanyLLM(KEY, "https://llm", "m", post=post).generate("x")
    assert e.value.kind == kind and str(e.value) == MESSAGES[kind]
    assert isinstance(e.value, CloudError)                   # the AI service handles every cloud engine alike


def test_CL_04_network_failure_and_the_key_never_leaks():
    _, post = recorder(raise_=OSError("boom"))
    with pytest.raises(CompanyLLMError) as e:
        CompanyLLM(KEY, "https://llm", "m", post=post).generate("x")
    assert e.value.kind == "network" and KEY not in str(e.value) and KEY not in repr(e.value)
    _, post = recorder(status=401, data=b"{}")
    with pytest.raises(CompanyLLMError) as e:
        CompanyLLM(KEY, "https://llm", "m", post=post).check()
    assert e.value.kind == "key" and KEY not in str(e.value)
    calls, post = recorder(data=answer("OK"))
    assert CompanyLLM(KEY, "https://llm", "m", post=post).check() is None
    assert "OK" in json.loads(calls[0][1])["messages"][0]["content"]
