"""Shrink a capture and turn it into a PDF - pure image maths, no UI and no Windows calls.

Resizing uses area averaging (best for shrinking). PDF is built with Pillow (offline, no external
program); a long scroll capture is split across A4 pages, or scaled to fit one page."""
from __future__ import annotations

import io

import cv2
import numpy as np

A4_PORTRAIT_PX = (794, 1123)        # A4 at 96 dpi (210 × 297 mm)
PAGE_MARGIN_PX = 38                 # ~10 mm


def _bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:           # BGRA cut-out: put the transparent parts on white
        a = img[:, :, 3:4].astype(np.float32) / 255
        return (img[:, :, :3] * a + 255 * (1 - a)).round().astype(np.uint8)
    return np.ascontiguousarray(img[:, :, :3])


def _scale(img: np.ndarray, w: int, h: int) -> np.ndarray:
    h0, w0 = img.shape[:2]
    w, h = max(1, min(w, w0)), max(1, min(h, h0))          # never upscale
    if (w, h) == (w0, h0):
        return img
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def resize_longest(img: np.ndarray, longest: int) -> np.ndarray:
    """Scale so the longer side is `longest` px (keeping the ratio); never enlarges."""
    h, w = img.shape[:2]
    if max(w, h) <= longest:
        return img
    k = longest / max(w, h)
    return _scale(img, round(w * k), round(h * k))


def resize_percent(img: np.ndarray, percent: float) -> np.ndarray:
    h, w = img.shape[:2]
    k = min(1.0, max(0.0, percent / 100.0))
    return _scale(img, round(w * k), round(h * k))


def estimate_bytes(img: np.ndarray, fmt: str = "png", quality: int = 85) -> int:
    """Encoded size. For a modest picture this just encodes it; for a big one it encodes a
    downscaled sample and scales the size up by the pixel ratio (fast enough for a live preview)."""
    src = _bgr(img)
    h, w = src.shape[:2]
    big = w * h > 1_200_000
    sample = resize_longest(src, 900) if big else src
    if fmt == "jpg":
        ok, buf = cv2.imencode(".jpg", sample, [cv2.IMWRITE_JPEG_QUALITY, quality])
    else:
        ok, buf = cv2.imencode(".png", sample, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        return w * h * 3
    n = int(buf.size)
    if big:
        n = int(n * (w * h) / max(1, sample.shape[0] * sample.shape[1]))
    return n


def resize_to_bytes(img: np.ndarray, budget: int, fmt: str = "jpg", quality: int = 85):
    """Shrink until the encoded picture is at most `budget` bytes. Returns (image, w, h)."""
    src = _bgr(img)
    h0, w0 = src.shape[:2]
    if estimate_bytes(src, fmt, quality) <= budget:
        return src, w0, h0
    lo, hi = 0.05, 1.0
    best = _scale(src, max(16, round(w0 * lo)), max(16, round(h0 * lo)))
    for _ in range(12):
        mid = (lo + hi) / 2
        cand = _scale(src, max(16, round(w0 * mid)), max(16, round(h0 * mid)))
        if estimate_bytes(cand, fmt, quality) <= budget:
            best, lo = cand, mid
        else:
            hi = mid
    return best, best.shape[1], best.shape[0]


def _to_bgr_tuple(color) -> tuple[int, int, int]:
    """Accept a (B, G, R) tuple/list or a '#RRGGBB' hex string; return a BGR int tuple."""
    if isinstance(color, str):
        s = color.lstrip("#")
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        return (b, g, r)
    return tuple(int(c) for c in color[:3])


def add_border(img: np.ndarray, thickness: int = 0, color=(0, 0, 0), shadow: bool = False,
               shadow_blur: int = 16, shadow_offset: tuple[int, int] = (8, 8),
               shadow_opacity: float = 0.35, bg=(255, 255, 255)) -> np.ndarray:
    """Put a solid border of `thickness` px (colour in BGR or '#RRGGBB') around the picture, and
    optionally a soft drop shadow. Returns an opaque BGR image on a `bg` background (so it pastes
    cleanly into docs); the picture itself is never enlarged or altered."""
    src = _bgr(img)
    t = max(0, int(thickness))
    col = _to_bgr_tuple(color)
    bordered = cv2.copyMakeBorder(src, t, t, t, t, cv2.BORDER_CONSTANT, value=col) if t else src
    if not shadow:
        return np.ascontiguousarray(bordered)
    bh, bw = bordered.shape[:2]
    ox, oy = int(shadow_offset[0]), int(shadow_offset[1])
    blur = max(1, int(shadow_blur))
    margin = blur * 2 + max(abs(ox), abs(oy)) + 2
    cw, ch = bw + 2 * margin, bh + 2 * margin
    bg_tuple = _to_bgr_tuple(bg)
    canvas = np.full((ch, cw, 3), bg_tuple, np.uint8).astype(np.float32)
    x0, y0 = margin, margin
    mask = np.zeros((ch, cw), np.float32)
    mask[y0 + oy:y0 + oy + bh, x0 + ox:x0 + ox + bw] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), blur) * float(max(0.0, min(1.0, shadow_opacity)))
    canvas *= (1.0 - mask[:, :, None])                       # multiply towards black = the shadow
    out = canvas.round().astype(np.uint8)
    out[y0:y0 + bh, x0:x0 + bw] = bordered                   # the picture sits on top, crisp
    return np.ascontiguousarray(out)


def rotate90(img: np.ndarray, degrees: int) -> np.ndarray:
    """A quarter turn: +90 clockwise, -90 counter-clockwise (any multiple of 90 works)."""
    q = (int(degrees) // 90) % 4
    if q == 0:
        return img
    code = {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}[q]
    return np.ascontiguousarray(cv2.rotate(img, code))


def _pil(img: np.ndarray):
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(_bgr(img), cv2.COLOR_BGR2RGB))


def _page(img, page_w, page_h):
    """One white A4 page with `img` placed at the top, centred horizontally, within the margins."""
    from PIL import Image
    page = Image.new("RGB", (page_w, page_h), "white")
    avail_w = page_w - 2 * PAGE_MARGIN_PX
    if img.width > avail_w:
        img = img.resize((avail_w, max(1, round(img.height * avail_w / img.width))))
    page.paste(img, (PAGE_MARGIN_PX, PAGE_MARGIN_PX))
    return page


def image_to_pdf(img: np.ndarray, dpi: float = 96, fit_one_page: bool = False,
                 page_px: tuple[int, int] = A4_PORTRAIT_PX) -> bytes:
    """PDF bytes. A tall capture is split across A4 pages, or (fit_one_page) scaled to one page."""
    pil = _pil(img)
    page_w, page_h = page_px
    avail_w = page_w - 2 * PAGE_MARGIN_PX
    avail_h = page_h - 2 * PAGE_MARGIN_PX
    if pil.width > avail_w:                                  # fit the width first
        pil = pil.resize((avail_w, max(1, round(pil.height * avail_w / pil.width))))
    pages = []
    if fit_one_page or pil.height <= avail_h:
        if pil.height > avail_h:
            pil = pil.resize((max(1, round(pil.width * avail_h / pil.height)), avail_h))
        pages = [_page(pil, page_w, page_h)]
    else:
        y = 0
        while y < pil.height:
            strip = pil.crop((0, y, pil.width, min(pil.height, y + avail_h)))
            pages.append(_page(strip, page_w, page_h))
            y += avail_h
    out = io.BytesIO()
    pages[0].save(out, "PDF", resolution=float(dpi), save_all=True, append_images=pages[1:])
    return out.getvalue()
