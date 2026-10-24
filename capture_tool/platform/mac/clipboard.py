"""macOS pasteboard. The app's payload uses Windows format names; PNG, HTML and text map to UTIs,
CF_DIB / GVML / SVG have no Mac reader and are dropped. `pasteboard_items` is pure; the
NSPasteboard calls need a Mac."""
from __future__ import annotations

import re

from ...core.clipboard_payload import HTML, PNG, UNICODE

_UTI = {PNG: "public.png", HTML: "public.html", UNICODE: "public.utf8-plain-text"}
_FRAGMENT = re.compile(r"<!--StartFragment-->(.*?)<!--EndFragment-->", re.S)


class ClipboardBusy(OSError):
    pass


def _html_of(value) -> str:
    """The HTML inside a CF_HTML wrapper (header lines + fragment markers), or the text as is."""
    text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)
    m = _FRAGMENT.search(text)
    if m:
        return m.group(1)
    i = text.find("<")
    return text[i:] if i >= 0 else text


def _text_of(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-16-le", "replace").rstrip("\x00")
    return str(value)


def pasteboard_items(payload: dict) -> dict[str, bytes | str]:
    out: dict[str, bytes | str] = {}
    for name, value in payload.items():
        uti = _UTI.get(name)
        if uti is None:
            continue
        if name == HTML:
            out[uti] = _html_of(value)
        elif name == UNICODE:
            out[uti] = _text_of(value)
        else:
            out[uti] = bytes(value)
    return out


def set_formats(payload: dict, retries: int = 5, delay: float = 0.02, hwnd=None) -> None:
    from AppKit import NSPasteboard
    from Foundation import NSData
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    for uti, value in pasteboard_items(payload).items():
        if isinstance(value, str):
            pb.setString_forType_(value, uti)
        else:
            pb.setData_forType_(NSData.dataWithBytes_length_(value, len(value)), uti)


def get_format(name: str, retries: int = 5, delay: float = 0.02) -> bytes | None:
    from AppKit import NSPasteboard
    uti = _UTI.get(name)
    if uti is None:
        return None
    d = NSPasteboard.generalPasteboard().dataForType_(uti)
    return bytes(d) if d is not None else None


def get_text() -> str | None:
    from AppKit import NSPasteboard
    s = NSPasteboard.generalPasteboard().stringForType_("public.utf8-plain-text")
    return str(s) if s is not None else None
