"""Web search for a capture: by its text (Google / Naver / Papago) or by the picture itself.
Picture search only opens the search page - the capture is on the clipboard and the person
pastes it there, so nothing is uploaded unless they do."""
from __future__ import annotations

from urllib.parse import quote, urlencode

MAX_QUERY = 300

_TEXT = {
    "google": ("https://www.google.com/search", "q", {}),
    "naver": ("https://search.naver.com/search.naver", "query", {}),
    "papago": ("https://papago.naver.com/", "st", {"sk": "auto", "tk": "ko"}),
}
# Google with its "이미지로 검색" box already open (Ctrl+V works at once). Naver has no picture
# search on the PC web (its Smart Lens is in the phone app), so it isn't offered.
_IMAGE = {
    "google": "https://www.google.com/?olud",
}
LABELS = {"google": "구글", "naver": "네이버", "papago": "파파고 번역"}


def text_url(engine: str, text: str) -> str | None:
    if engine not in _TEXT:
        raise ValueError(f"unknown search engine {engine!r}")
    q = " ".join((text or "").split())[:MAX_QUERY]
    if not q:
        return None
    base, key, extra = _TEXT[engine]
    return base + "?" + urlencode({**extra, key: q}, quote_via=quote)


def image_page(engine: str) -> str:
    if engine not in _IMAGE:
        raise ValueError(f"unknown search engine {engine!r}")
    return _IMAGE[engine]
