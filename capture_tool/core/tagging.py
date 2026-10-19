"""What a saved capture looks like and is about, for 캡처 찾기 - computed on the PC when the
picture is saved: a perceptual hash (finds the same screen captured again), its main colours, the
kind of content (photo / table / code / text / UI), its size class and the words its text is
mostly about. No model, a few milliseconds per picture."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

from .ocr import OcrLine, looks_like_photo

KINDS = {"area": "영역", "window": "창", "fullscreen": "전체화면", "scroll": "스크롤", "table": "표", "pin": "고정",
         "file": "파일"}
CONTENT = {"photo": "사진", "table": "표", "code": "코드", "text": "글", "ui": "화면"}
SIZE = {"full": "전체 화면", "window": "창 크기", "piece": "조각"}
COLOURS = ["빨강", "주황", "노랑", "초록", "청록", "파랑", "보라", "분홍", "검정", "흰색", "회색"]
_HUE_BINS = [(0, 10, "빨강"), (10, 22, "주황"), (22, 38, "노랑"), (38, 85, "초록"), (85, 100, "청록"), (100, 130, "파랑"),
             (130, 155, "보라"), (155, 170, "분홍"), (170, 181, "빨강")]
COLOUR_SHARE = 0.05       # a colour counts when it covers this share of the picture
GREY_SAT = 40             # below: no hue - black / white / grey by brightness
INK = 60                  # a pixel this far from the paper colour is ink
RULE_SHARE = 0.6          # a row/column with ink over this share of the width/height is a rule
CODE_SHARE = 0.4          # lines with code symbols
TEXT_AREA = 0.2           # text boxes covering this share of the picture = a text picture
THUMB_W, THUMB_H = 264, 168
_PARTICLES = ("에서", "으로", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도")
_WORD = re.compile(r"[0-9A-Za-z가-힣_]+")
_CODE_SYMBOLS = re.compile(r"[{}();=<>\[\]]|->|=>|::|#include|\bdef\b|\breturn\b|\bimport\b|\bconst\b|\bvar\b|\blet\b")


@dataclass(frozen=True)
class CaptureMeta:
    kind: str = "area"            # area / window / fullscreen / scroll / table / pin / file
    app: str = ""                 # exe name of the window captured, lower case, without .exe
    title: str = ""               # that window's title
    taken: str = ""               # ISO date-time of the capture


@dataclass(frozen=True)
class Described:
    w: int
    h: int
    phash: int
    colors: tuple[str, ...]
    content: str
    size_class: str


# --- looks -------------------------------------------------------------------------------------
def _gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)


def phash(img: np.ndarray) -> int:
    """64-bit DCT hash: 32x32 grey, the 8x8 lowest frequencies against their median."""
    g = cv2.resize(_gray(img), (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = cv2.dct(g)[:8, :8].flatten()
    med = float(np.median(d[1:]))
    bits = 0
    for v in d:
        bits = (bits << 1) | int(v > med)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def colour_names(img: np.ndarray, n: int = 3) -> list[str]:
    if img is None or img.size == 0 or img.ndim != 3:
        return []
    h, w = img.shape[:2]
    k = 120 / max(h, w)
    small = cv2.resize(img[:, :, :3], None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img[:, :, :3]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    hue, sat, val = hsv[:, 0].astype(int), hsv[:, 1].astype(int), hsv[:, 2].astype(int)
    grey = sat < GREY_SAT
    counts: Counter = Counter()
    counts["검정"] = int(np.count_nonzero(grey & (val < 60)))
    counts["흰색"] = int(np.count_nonzero(grey & (val >= 200)))
    counts["회색"] = int(np.count_nonzero(grey & (val >= 60) & (val < 200)))
    for lo, hi, name in _HUE_BINS:
        counts[name] += int(np.count_nonzero(~grey & (hue >= lo) & (hue < hi)))
    total = max(1, hsv.shape[0])
    return [name for name, c in counts.most_common() if c / total >= COLOUR_SHARE][:n]


def _ink(img: np.ndarray) -> np.ndarray:
    g = _gray(img)
    paper = int(np.median(g))
    return np.abs(g.astype(np.int16) - paper) > INK


def _is_grid(img: np.ndarray) -> bool:
    ink = _ink(img)
    if ink.size == 0:
        return False
    rows = ink.mean(axis=1) >= RULE_SHARE
    cols = ink.mean(axis=0) >= RULE_SHARE
    return _runs(rows) >= 3 and _runs(cols) >= 2


def _runs(flags: np.ndarray) -> int:
    f = flags.astype(np.int8)
    return int(np.count_nonzero(np.diff(np.concatenate(([0], f))) == 1))


def _is_code(lines: list[OcrLine]) -> bool:
    texts = [l.text for l in lines if l.text.strip()]
    if len(texts) < 4:
        return False
    hits = sum(1 for t in texts if _CODE_SYMBOLS.search(t))
    return hits >= 3 and hits / len(texts) >= CODE_SHARE


def content_kind(img: np.ndarray, lines: list[OcrLine] | None) -> str:
    if img is None or img.size == 0:
        return "ui"
    if looks_like_photo(img):
        return "photo"
    if _is_grid(img):
        return "table"
    if lines:
        if _is_code(lines):
            return "code"
        area = sum(l.box[2] * l.box[3] for l in lines)
        if area / float(img.shape[0] * img.shape[1]) >= TEXT_AREA:
            return "text"
    return "ui"


def size_class(w: int, h: int, screen: tuple[int, int] | None = None) -> str:
    sw, sh = screen or (1920, 1080)
    if w >= 0.9 * sw and h >= 0.9 * sh:
        return "full"
    if w >= 500 and h >= 300:
        return "window"
    return "piece"


def thumbnail(img: np.ndarray) -> bytes:
    """A small JPEG for result grids (fits THUMB_W x THUMB_H)."""
    h, w = img.shape[:2]
    k = min(THUMB_W / max(1, w), THUMB_H / max(1, h), 1.0)
    small = cv2.resize(img[:, :, :3], (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA) \
        if k < 1 else img[:, :, :3]
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def describe(img: np.ndarray, lines: list[OcrLine] | None = None, screen: tuple[int, int] | None = None) -> Described:
    h, w = img.shape[:2]
    return Described(w, h, phash(img), tuple(colour_names(img)), content_kind(img, lines), size_class(w, h, screen))


# --- words -------------------------------------------------------------------------------------
def _words(text: str) -> list[str]:
    out = []
    for tok in _WORD.findall(text or ""):
        if len(tok) < 2 or tok[0].isdigit():
            continue
        for p in _PARTICLES:
            if tok.endswith(p) and len(tok) - len(p) >= 2 and re.search(r"[가-힣]", tok):
                tok = tok[:-len(p)]
                break
        out.append(tok.lower())
    return out


def keywords(lines: list[OcrLine] | None, n: int = 5) -> list[str]:
    """The words the text uses most (2+ letters, no numbers, Korean particles dropped)."""
    if not lines:
        return []
    order: dict[str, int] = {}
    counts: Counter = Counter()
    for l in lines:
        for wd in _words(l.text):
            counts[wd] += 1
            order.setdefault(wd, len(order))
    ranked = sorted(counts, key=lambda wd: (-counts[wd], order[wd]))
    return ranked[:n]


def auto_tags(meta: CaptureMeta, d: Described, lines: list[OcrLine] | None = None) -> list[str]:
    tags = [KINDS.get(meta.kind, meta.kind)]
    if meta.app:
        tags.append(meta.app)
    tags.append(CONTENT.get(d.content, d.content))
    tags += list(d.colors)
    tags += keywords(lines, 5)
    title_words = [wd for wd in _words(meta.title) if wd != meta.app][:5]
    tags += title_words
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
