"""The one error type the AI service handles for any cloud engine (Gemini at home, the company
LLM at work): a `kind` the UI can explain and a message in the person's words."""
from __future__ import annotations


class CloudError(Exception):
    MESSAGES: dict[str, str] = {}

    def __init__(self, kind: str, message: str | None = None):
        super().__init__(message or self.MESSAGES.get(kind, self.MESSAGES.get("other", kind)))
        self.kind = kind
