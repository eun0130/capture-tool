"""Build the set of clipboard formats for each copy mode, so any target app can
pick the richest format it understands."""
from __future__ import annotations

import html
import re
import struct

import numpy as np

UNICODE = "CF_UNICODETEXT"
HTML = "HTML Format"
PNG = "PNG"
DIB = "CF_DIB"
GVML = "Art::GVML ClipFormat"
SVG = "image/svg+xml"

_HEADER = ("Version:0.9\r\nStartHTML:{0:010d}\r\nEndHTML:{1:010d}\r\n"
           "StartFragment:{2:010d}\r\nEndFragment:{3:010d}\r\n")


def cf_html(fragment: str) -> bytes:
    """Windows "HTML Format": ASCII header with UTF-8 byte offsets."""
    pre = b"<html><head><meta charset=\"utf-8\"></head><body>\r\n<!--StartFragment-->"
    post = b"<!--EndFragment-->\r\n</body></html>"
    frag = fragment.encode("utf-8")
    head_len = len(_HEADER.format(0, 0, 0, 0).encode("ascii"))
    start_html = head_len
    start_frag = start_html + len(pre)
    end_frag = start_frag + len(frag)
    end_html = end_frag + len(post)
    head = _HEADER.format(start_html, end_html, start_frag, end_frag).encode("ascii")
    return head + pre + frag + post


def _crlf(text: str) -> str:
    return re.sub(r"\r\n|\r|\n", "\r\n", text)


def _cell(v: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", v)


def text_payload(text: str, table: list[list[str]] | None = None) -> dict:
    if table:
        plain = "\r\n".join("\t".join(_cell(c) for c in row) for row in table)
        rows = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in table)
        frag = f"<table>{rows}</table>"
    else:
        if not text or not text.strip():
            raise ValueError("no text to copy")
        plain = _crlf(text)
        frag = "<div>" + "<br>".join(html.escape(l) for l in plain.split("\r\n")) + "</div>"
    return {UNICODE: plain, HTML: cf_html(frag)}


def image_payload(png: bytes, dib: bytes) -> dict:
    if not png or not dib:
        raise ValueError("empty image data")
    return {PNG: png, DIB: dib}


def shapes_payload(gvml: bytes, svg_text: str, png: bytes) -> dict:
    return {GVML: gvml, SVG: svg_text.encode("utf-8"), PNG: png}


def dib_from_bgr(img: np.ndarray) -> bytes:
    """CF_DIB: BITMAPINFOHEADER + bottom-up 32-bit BGRA pixels."""
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=-1)
    h, w = img.shape[:2]
    if img.shape[2] == 3:
        bgra = np.concatenate([img, np.full((h, w, 1), 255, np.uint8)], axis=2)
    else:
        bgra = img[:, :, :4]
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0, w * h * 4, 2835, 2835, 0, 0)
    return header + np.ascontiguousarray(bgra[::-1]).tobytes()
