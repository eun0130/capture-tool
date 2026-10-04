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


_NUMBER = re.compile(r"[+-]?(\d[\d,]*)?\.?\d+%?")
_NOWRAP = "white-space:nowrap"           # Excel would wrap into narrow default columns (tall rows)
_AS_TEXT = "<td style='" + _NOWRAP + ";mso-number-format:\"\\@\"'>"
_PLAIN = "<td style='" + _NOWRAP + "'>"


def _keep_as_text(v: str) -> bool:
    """Cells Excel would change on paste: a formula (text read off a screen must never run)
    or a code whose leading zeros would be dropped."""
    v = v.strip()
    if re.fullmatch(r"0\d+", v):
        return True
    return len(v) > 1 and v[0] in "=+-@" and not _NUMBER.fullmatch(v)


def _td(v: str) -> str:
    return (_AS_TEXT if _keep_as_text(v) else _PLAIN) + html.escape(v) + "</td>"


def text_payload(text: str, table: list[list[str]] | None = None) -> dict:
    if table:
        plain = "\r\n".join("\t".join(_cell(c) for c in row) for row in table)
        rows = "".join("<tr>" + "".join(_td(c) for c in row) + "</tr>" for row in table)
        frag = f"<table>{rows}</table>"
    else:
        if not text or not text.strip():
            raise ValueError("no text to copy")
        plain = _crlf(text)
        frag = "<div>" + "<br>".join(html.escape(l) for l in plain.split("\r\n")) + "</div>"
    return {UNICODE: plain, HTML: cf_html(frag)}


def table_payload(rows: list[list[str]], style=None, title: str | None = None, runs: dict | None = None) -> dict:
    """A table for Excel / PowerPoint / Word: TSV + HTML; with `style` (TableStyle) the HTML
    carries the captured fills, text colours, bold header and borders."""
    runs = runs if style is not None else None         # plain look: black text throughout

    def inner(v: str, r: int, c: int) -> str:
        parts = (runs or {}).get((r, c))
        if not parts or "".join(t for t, _ in parts).strip() != v.strip():
            return html.escape(v)
        return "".join(f"<span style='color:{col}'>{html.escape(t)}</span>" if col else html.escape(t)
                       for t, col in parts)

    def td(v: str, r: int, c: int = 0) -> str:
        if style is None:
            return _td(v)
        fill = style.header_fill if r == 0 else style.body_fill
        color = style.header_text if r == 0 else style.body_text
        css = f"{_NOWRAP};background:{fill};color:{color};font-size:{style.font_size:g}pt"
        if r == 0 and style.header_bold:
            css += ";font-weight:bold"
        if style.border:
            css += f";border:1px solid {style.border}"
        if _keep_as_text(v):
            css += ';mso-number-format:"\\@"'
        return f"<td style='{css}'>" + inner(v, r, c) + "</td>"
    body = "".join("<tr>" + "".join(td(v, r, c) for c, v in enumerate(row)) + "</tr>" for r, row in enumerate(rows))
    frag = (f"<p>{html.escape(title)}</p>" if title else "") + \
        ("<table style='border-collapse:collapse'>" if style else "<table>") + body + "</table>"
    plain = "\r\n".join("\t".join(_cell(c) for c in row) for row in rows)
    if title:
        plain = _cell(title) + "\r\n" + plain
    return {UNICODE: plain, HTML: cf_html(frag)}


def image_payload(png: bytes, dib: bytes) -> dict:
    if not png or not dib:
        raise ValueError("empty image data")
    return {PNG: png, DIB: dib}


def shapes_payload(gvml: bytes, svg_text: str, png: bytes) -> dict:
    return {GVML: gvml, SVG: svg_text.encode("utf-8"), PNG: png}


def _ppm(dpi: float) -> int:
    return round(dpi / 0.0254)  # pixels per metre


def dib_from_bgr(img: np.ndarray, dpi: float = 96) -> bytes:
    """CF_DIB: BITMAPINFOHEADER + bottom-up 32-bit BGRA pixels, tagged with the screen dpi."""
    if img.ndim == 2:
        img = np.stack([img] * 3, axis=-1)
    h, w = img.shape[:2]
    if img.shape[2] == 3:
        bgra = np.concatenate([img, np.full((h, w, 1), 255, np.uint8)], axis=2)
    else:
        bgra = img[:, :, :4]
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0, w * h * 4, _ppm(dpi), _ppm(dpi), 0, 0)
    return header + np.ascontiguousarray(bgra[::-1]).tobytes()


def png_with_dpi(png: bytes, dpi: float) -> bytes:
    """Add (or replace) the PNG pHYs chunk so Office/Word place the picture at the size it had
    on screen: a 150% display has 144 physical pixels per inch, not 96."""
    import zlib
    sig, pos = png[:8], 8
    chunks = []
    while pos < len(png):
        n = struct.unpack(">I", png[pos:pos + 4])[0]
        kind = png[pos + 4:pos + 8]
        chunks.append((kind, png[pos:pos + 12 + n]))
        pos += 12 + n
    data = struct.pack(">IIB", _ppm(dpi), _ppm(dpi), 1)
    phys = struct.pack(">I", len(data)) + b"pHYs" + data + struct.pack(">I", zlib.crc32(b"pHYs" + data))
    out = [sig]
    for kind, raw in chunks:
        if kind == b"pHYs":
            continue
        out.append(raw)
        if kind == b"IHDR":
            out.append(phys)
    return b"".join(out)
