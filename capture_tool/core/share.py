"""Links to a capture: a file link (where the saved file is — nothing uploaded) and an internet
link (the picture is uploaded to Litterbox, a free temporary host that deletes it by itself
after 1 h / 12 h / 24 h / 72 h; anyone with the link can open it until then)."""
from __future__ import annotations

import uuid
from pathlib import Path, PureWindowsPath
from typing import Callable

UPLOAD_URL = "https://litterbox.catbox.moe/resources/internals/api.php"
LINK_PREFIX = "https://litter.catbox.moe/"
EXPIRIES = ["1h", "12h", "24h", "72h"]
EXPIRY_NAMES = {"1h": "1시간", "12h": "12시간", "24h": "24시간", "72h": "3일"}
TIMEOUT = 60


class ShareError(Exception):
    pass


def file_link(path: Path) -> tuple[str, str]:
    """(path to show/paste, file:// URL). A network folder (\\\\server\\share) gives a link that
    colleagues with access to that folder can open."""
    from urllib.parse import quote
    p = PureWindowsPath(str(path))
    text = str(p)
    if text.startswith("\\\\"):                              # \\server\share\... -> file://server/share/...
        server, _, rest = text[2:].partition("\\")
        return text, f"file://{server}/" + quote(rest.replace("\\", "/"))
    return text, "file:///" + quote(text.replace("\\", "/"), safe="/:")


def link_html(url: str, label: str) -> str:
    from html import escape
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def _post(url: str, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def upload_litterbox(png: bytes, expiry: str = "24h", post: Callable | None = None,
                     timeout: float = TIMEOUT) -> str:
    """Upload a PNG; returns its https link. Raises ShareError with a message for the user."""
    if expiry not in EXPIRIES:
        raise ValueError(f"expiry must be one of {EXPIRIES}")
    boundary = "----CaptureTool" + uuid.uuid4().hex
    parts = []
    for name, value in (("reqtype", "fileupload"), ("time", expiry)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="fileToUpload"; filename="capture.png"\r\n'
                 "Content-Type: image/png\r\n\r\n".encode() + png + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "CaptureTool"}
    try:
        status, data = (post or _post)(UPLOAD_URL, body, headers, timeout)
    except OSError as e:
        raise ShareError("인터넷에 연결하지 못했습니다. 연결을 확인하고 다시 해 주세요.") from e
    text = (data or b"").decode("utf-8", "replace").strip()
    if status != 200 or not text.startswith(LINK_PREFIX) or any(c.isspace() for c in text):
        raise ShareError("이미지를 올리지 못했습니다. 잠시 뒤 다시 해 주세요.")
    return text
