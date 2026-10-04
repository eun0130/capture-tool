"""Offline OCR (RapidOCR + ONNX, Korean PP-OCRv5). Loaded lazily, warmed up in the
background at startup so the first recognition does not wait for model loading."""
from __future__ import annotations

import importlib.util
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

MIN_SCORE = 0.5


class OcrUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrLine:
    text: str
    box: tuple  # (x, y, w, h)
    score: float


# Model files that must ship with the app. RapidOCR silently downloads any that are missing
# from the internet; we refuse instead (the app promises to work offline).
REQUIRED_MODELS = ["ch_PP-OCRv5_det_mobile.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                   "korean_PP-OCRv5_rec_mobile.onnx"]
LATIN_MODELS = ["PP-OCRv6_rec_small.onnx"]          # one reader for English and European languages
# ONNX Runtime defaults to one thread per core per model (≈45 threads per engine on 32 cores).
def ocr_threads(cores: int | None) -> int:
    """Half the cores, at most 8: recognition is short and bursty, so more threads finish it
    sooner (4 -> 8 measured 25% faster on a 32-core PC) while half the PC stays free."""
    return max(1, min(8, (cores or 4) // 2))


OCR_THREADS = ocr_threads(os.cpu_count())


def model_dir() -> Path:
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        return Path("__missing__")
    return Path(spec.origin).parent / "models"


def missing_models(names: list[str]) -> list[str]:
    d = model_dir()
    return [n for n in names if not (d / n).is_file()]


def ocr_params(lang: str) -> dict:
    LangRec, ModelType, OCRVersion = _rapidocr("LangRec", "ModelType", "OCRVersion")

    return {
        "Global.log_level": "error",
        "Global.max_side_len": 4000,       # tiles are at most 3800 wide; never shrink them
        "Global.use_cls": False,  # screenshots are upright; the classifier flips digit lines
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        # Korean dictionary also covers plain Latin letters/digits; LATIN covers é ç ñ ß ¿ ...
        "Rec.lang_type": LangRec.KOREAN if lang == "korean" else LangRec.EN,
        "Rec.ocr_version": OCRVersion.PPOCRV5 if lang == "korean" else OCRVersion.PPOCRV6,
        "Rec.model_type": ModelType.MOBILE if lang == "korean" else ModelType.SMALL,
        "EngineConfig.onnxruntime.intra_op_num_threads": OCR_THREADS,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }


_import_lock = threading.Lock()


def _rapidocr(*names: str):
    """rapidocr names (default: the RapidOCR class), imported without touching the network.

    rapidocr imports requests/urllib3 for model downloads (never used here: models ship with
    the app). At import urllib3 probes IPv6 by creating a socket, and on PCs with online-banking
    security software that socket call can hang for good — the OCR warm-up then holds the
    import lock and every text feature (and the selftest) freezes. With `socket.has_ipv6`
    False the probe is skipped; the flag is restored right after."""
    import socket
    with _import_lock:
        saved = socket.has_ipv6
        socket.has_ipv6 = False
        try:
            import rapidocr
            found = [getattr(rapidocr, n) for n in (names or ("RapidOCR",))]
        finally:
            socket.has_ipv6 = saved
    return found[0] if len(found) == 1 else found


def _build_rapidocr(params: dict):
    return _rapidocr()(params=params)


def _require(names: list[str]) -> None:
    missing = missing_models(names)
    if missing:
        raise OcrUnavailable("텍스트 인식 모델 파일이 없습니다(다시 설치해 주세요): " + ", ".join(missing))


def default_factory():
    _require(REQUIRED_MODELS)
    return _build_rapidocr(ocr_params("korean"))


def latin_factory():
    """Recognizer for Latin-script languages (French, Spanish, German, Italian, Portuguese, ...).
    Used for recognition only, so its detector/classifier sessions are released right away."""
    _require(REQUIRED_MODELS + LATIN_MODELS)
    eng = _build_rapidocr(ocr_params("latin"))
    eng.text_det = None  # never used: we call it with use_det=False on line crops
    eng.text_cls = None
    return eng


def latin_recognize(engine, crop, _primary_text):
    """Recognition only (no detection) of one text-line crop -> (text, score) or None."""
    r = engine(crop, use_det=False, use_cls=False, use_rec=True)
    if r is None or not r.txts:
        return None
    return str(r.txts[0]), float(r.scores[0])


_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")
SMALL_LINE_PX = 48            # English/European lines lower than this are enlarged before the second reading
SECOND_READING_MARGIN = 0.05  # prefer the Latin reading unless clearly less confident


MARGIN = 24              # px added around a low piece before reading (its own border colour)
MARGIN_LOW = MARGIN
LOW_PIECE = 100


def with_margin(img: np.ndarray, m: int) -> np.ndarray:
    """The image with an m-pixel frame in the median colour of its own border."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img = img[:, :, :3]
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    bg = np.median(border, axis=0).astype(np.uint8)
    out = np.empty((img.shape[0] + 2 * m, img.shape[1] + 2 * m, 3), np.uint8)
    out[:] = bg
    out[m:m + img.shape[0], m:m + img.shape[1]] = img
    return out


def needs_latin(text: str) -> bool:
    return not _HANGUL.search(text) and bool(_LATIN_LETTER.search(text))


def fix_mixed_line(original: str, latin: str) -> str | None:
    """Put the Latin model's letters and digits into the original text, keeping the original's
    separators ("·" stays "·" where the Latin model wrote "-"). None when the two disagree on
    how many letters/digits there are (then the first reading is kept)."""
    if not latin or _HANGUL.search(latin):
        return None
    src = [i for i, ch in enumerate(original) if ch.isalnum()]
    new = [ch for ch in latin if ch.isalnum()]
    if not src:
        return None
    if len(src) == len(new):
        out = list(original)
        for i, ch in zip(src, new):
            out[i] = ch
        return "".join(out)
    # a letter lost or added: match part by part ("Giäub" -> "GitHub"), keeping the separators
    parts_o = re.split(r"([^\w]+)", original)
    parts_n = [p for p in re.split(r"[^\w]+", latin) if p]
    words_o = [p for p in parts_o[::2] if p]
    if len(words_o) < 2 or len(words_o) != len(parts_n):
        return None
    if any(abs(len(a) - len(b)) > 1 for a, b in zip(words_o, parts_n)):
        return None
    it = iter(parts_n)
    return "".join((next(it) if (k % 2 == 0 and p) else p) for k, p in enumerate(parts_o))


def arrow_kind(mask: np.ndarray) -> str | None:
    """A drawn arrow from its pixels: one row of ink runs (nearly) its whole width - the shaft -
    and there is a head (clearly taller than the shaft) at both ends, the right one or the left one."""
    h, w = mask.shape
    if h < 3 or w < 6 or w < 1.1 * h:
        return None
    mid = mask.sum(axis=1)[max(0, h // 4):max(1, h - h // 4)]
    if mid.size == 0 or mid.max() < 0.85 * w:
        return None                                   # no shaft through the middle: a letter, not an arrow
    counts = mask.sum(axis=0)
    shaft = int(counts[w // 3:max(w // 3 + 1, 2 * w // 3)].min())
    side = max(1, int(w * 0.4))
    need = max(shaft + 2, 1.6 * shaft)
    lh = counts[:side].max() >= need
    rh = counts[w - side:].max() >= need
    if lh and rh:
        return "↔"
    if rh:
        return "→"
    if lh:
        return "←"
    return None


ARROWS = ("→", "←", "↔", "->", "<-", "<->")


def _arrow_in(img: np.ndarray, box) -> str | None:
    """The arrow drawn inside box (its biggest piece of ink), by shape."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    crop = img[max(0, y0 - 1):y1 + 1, max(0, x0 - 1):x1 + 1]
    if crop.size == 0:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(int) if crop.ndim == 3 else crop.astype(int)
    ink = (np.abs(g - int(np.median(g))) > 60).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n < 2:
        return None
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in st[k][:4])
    return arrow_kind(lab[y:y + h, x:x + w] == k)


def fill_dropped_arrows(img: np.ndarray, text: str, box) -> str:
    """The readers don't know "↔" and sometimes drop arrows: one drawn in the word's box but
    missing from its text is put back - in a double space it left, or at the word's start/end."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, x1 = x0 - 3, x1 + 3                               # the box can clip an arrow's tip
    crop = img[max(0, y0):y1, max(0, x0):x1]
    if crop.size == 0:
        return text
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(int) if crop.ndim == 3 else crop.astype(int)
    ink = (np.abs(g - int(np.median(g))) > 60).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    th = ink.shape[0]
    arrows, others = [], []
    for k in range(1, n):
        x, y, w, h, a = (int(v) for v in st[k])
        kind = arrow_kind(lab[y:y + h, x:x + w] == k) if (h <= 0.6 * th and w >= 1.1 * h and w >= 6) else None
        (arrows if kind else others).append((x, x + w, kind))
    have = [m for m in re.finditer("[→←↔]", text)]
    if have and len(have) == len(arrows):                 # the reader knows → and ←, not ↔:
        out = list(text)                                  # only a double-headed shape changes it
        for m, (_, _, kind) in zip(have, sorted(arrows)):
            if kind == "↔":
                out[m.start()] = kind
        return "".join(out)
    missing = len(arrows) - len(have)
    if missing <= 0 or not others:
        return text
    gaps = list(re.finditer(r"  +", text))
    if len(gaps) == len(arrows):
        parts = re.split(r"  +", text)
        out = parts[0]
        for (_, _, kind), part in zip(sorted(arrows), parts[1:]):
            out += f" {kind} " + part
        return out
    first, last = min(o[0] for o in others), max(o[1] for o in others)
    for x, x2, kind in sorted(arrows):
        if x2 <= first and not text.lstrip().startswith(kind):
            text = f"{kind} {text.lstrip()}"
        elif x >= last and not text.rstrip().endswith(kind):
            text = f"{text.rstrip()} {kind}"
    return text


_ODD_LATIN_BY_HANGUL = re.compile(r"[\u00c0-\u024f][\uac00-\ud7a3]|[\uac00-\ud7a3][\u00c0-\u024f]")
_PRONOUN_L = re.compile(r"(?<![\w.,'’])l(?=(['’](m|ll|ve|d))?(?![\w'’]))")
_CAPS_WORD = re.compile(r"(?<![\w'’-])[A-Za-z]{2,6}(?![\w'’-])")     # "Al-Rashid" is a name
_SHORT_CAPS = {"Al": "AI", "Cl": "CI", "Ul": "UI"}      # "El" (Spanish) and the like stay


def fix_capital_i(text: str) -> str:
    """In sans-serif fonts capital I and small l look the same. "Al"/"Cl"/"Ul" are AI/CI/UI, a
    longer word of capitals with an l in it ("KPl", "APl") gets an I, and in English a lone
    "l" ("so l can", "l'm") is the pronoun I. Ordinary words are left alone."""
    if not text:
        return text

    def repl(m):
        w = m.group(0)
        if w in _SHORT_CAPS:
            return _SHORT_CAPS[w]
        rest = w.replace("l", "")
        if len(w) >= 3 and "l" in w and rest.isupper() and sum(c.isupper() for c in rest) >= 2:
            return w.replace("l", "I")
        return w
    text = _CAPS_WORD.sub(repl, text)
    if re.search(r"[A-Za-z]", text.replace("l", "")) and not _HANGUL.search(text):
        text = _PRONOUN_L.sub("I", text)
    return text


def _latin_runs(word: str) -> list[tuple[int, int]]:
    """Index ranges of the English parts of a word. A single Hangul letter between two Latin
    letters ("Gi채ub") is a misread inside an English word and belongs to it."""
    def latin_at(i: int) -> bool:
        ch = word[i]
        if not _HANGUL.search(ch):
            return True
        return (0 < i < len(word) - 1 and word[i - 1].isascii() and word[i - 1].isalpha()
                and word[i + 1].isascii() and word[i + 1].isalpha())
    runs, start = [], None
    for i in range(len(word) + 1):
        if i < len(word) and latin_at(i):
            start = i if start is None else start
        elif start is not None:
            if _LATIN_LETTER.search(word[start:i]):
                runs.append((start, i))
            start = None
    return runs


def _char_weight(ch: str) -> float:
    if _HANGUL.search(ch) or "\u3040" <= ch <= "\u9fff":
        return 1.0
    if ch.isascii() and ch.isalnum():
        return 0.6
    return 0.4


class OcrEngine:
    def __init__(self, factory: Callable | None = None, secondary_factory: Callable | None = None,
                 secondary_call: Callable | None = None, margin: int | None = None):
        self._factory = factory or default_factory
        # text touching the image edge is missed by the text finder ("매입처별…" cut tight read
        # as "매 ㅎ"): every piece is read with a margin of its own border colour around it
        self.margin = (MARGIN if factory is None else 0) if margin is None else margin
        if secondary_factory is None and factory is None:
            secondary_factory = latin_factory
        self._secondary_factory = secondary_factory
        self._secondary_call = secondary_call or latin_recognize
        self._secondary = None
        self._secondary_failed = False
        self._engine = None
        self._error: Exception | None = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._engine is not None

    def _load(self):
        with self._lock:
            if self._engine is None and self._error is None:
                try:
                    self._engine = self._factory()
                except Exception as e:  # noqa: BLE001 - any load failure disables OCR only
                    self._error = e
            if self._error is not None:
                raise OcrUnavailable(f"텍스트 인식 엔진을 불러오지 못했습니다: {self._error}")
            return self._engine

    def _load_secondary(self):
        if self._secondary_factory is None or self._secondary_failed:
            return None
        with self._lock:
            if self._secondary is None and not self._secondary_failed:
                try:
                    self._secondary = self._secondary_factory()
                except Exception:  # noqa: BLE001 - missing Latin model only disables the second reading
                    self._secondary_failed = True
            return self._secondary

    def warmup(self) -> threading.Thread:
        """Load the main (Korean/English) model in the background. The Latin model is loaded
        only the first time a Latin-script line shows up, so it costs nothing until needed."""
        def run():
            try:
                self._load()
            except OcrUnavailable:
                pass
        t = threading.Thread(target=run, name="ocr-warmup", daemon=True)
        t.start()
        return t

    def recognize(self, img: np.ndarray | None) -> list[OcrLine]:
        """Big images (scroll captures, 4K screens) go in overlapping tiles: the recognizer
        shrinks anything over 2000 px, which garbles text. A line is kept from the tile that
        owns its centre, so lines in an overlap are reported once."""
        if img is None or img.size == 0 or min(img.shape[:2]) < 4:
            return []
        engine = self._load()
        h, w = img.shape[:2]
        parts = tiles(w, h)
        lines = []
        for x0, y0, tw, th in parts:
            own = _owned(x0, y0, tw, th, w, h)
            if len(parts) > 1:                   # big image: leave out blank paper
                box = _ink_box(img[y0:y0 + th, x0:x0 + tw])
                if box is None:
                    continue
                ix, iy, iw, ih = box
                tile_lines = self._run_margined(engine, img[y0 + iy:y0 + iy + ih, x0 + ix:x0 + ix + iw],
                                                x0 + ix, y0 + iy, w, h)
            else:
                tile_lines = self._run_margined(engine, img[y0:y0 + th, x0:x0 + tw], x0, y0, w, h)
            for line in tile_lines:
                bx, by, bw, bh = line.box
                cx, cy = bx + bw / 2, by + bh / 2
                if own[0] <= cx < own[2] and own[1] <= cy < own[3]:
                    lines.append(line)
        lines = [OcrLine(fix_capital_i(l.text), l.box, l.score) for l in lines]
        return reading_order(lines)

    def _run_margined(self, engine, piece: np.ndarray, x0: int, y0: int, w: int, h: int) -> list[OcrLine]:
        m = self.margin
        if m <= 0:
            return self._run_tile(engine, piece, x0, y0)
        if piece.shape[0] >= LOW_PIECE:           # only low (one-line) pieces lose text at the edge;
            return self._run_tile(engine, piece, x0, y0)   # bigger ones read best as they are
        m = MARGIN_LOW
        out = []
        for line in self._run_tile(engine, with_margin(piece, m), x0 - m, y0 - m):
            bx, by, bw, bh = line.box                 # back inside the image
            nx, ny = max(0, bx), max(0, by)
            nw, nh = min(w, bx + bw) - nx, min(h, by + bh) - ny
            if nw > 0 and nh > 0:
                out.append(OcrLine(line.text, (nx, ny, nw, nh), line.score))
        return out

    def _run_tile(self, engine, img: np.ndarray, x0: int, y0: int) -> list[OcrLine]:
        img = np.ascontiguousarray(img) if not img.flags["C_CONTIGUOUS"] else img
        try:                                      # flags every time: RapidOCR keeps the last call's
            r = engine(img, use_det=True, use_cls=False, use_rec=True, return_word_box=True)
        except TypeError:
            try:
                r = engine(img, return_word_box=True)
            except TypeError:                     # engines without word boxes (older / test fakes)
                r = engine(img)
        if r is None or r.txts is None or r.boxes is None:
            return []
        words_all = list(getattr(r, "word_results", None) or ())
        pieces = []
        for k, (quad, text, score) in enumerate(zip(r.boxes, r.txts, r.scores)):
            if float(score) < MIN_SCORE or not str(text).strip():
                continue
            q = np.asarray(quad, float)
            x, y = q[:, 0].min(), q[:, 1].min()
            box = (int(round(x)), int(round(y)), int(round(q[:, 0].max() - x)), int(round(q[:, 1].max() - y)))
            pieces.append([str(text), box, float(score), words_all[k] if k < len(words_all) else ()])
        out = []
        for text, box, score, words in self._join_pieces(engine, img, pieces):
            if _HANGUL.search(text) and _LATIN_LETTER.search(text) and words:
                text = self._fix_latin_words(img, text, words or ())
            line = self._second_reading(img, OcrLine(text, box, float(score)))
            bx, by, bw, bh = line.box
            out.append(OcrLine(line.text, (bx + x0, by + y0, bw, bh), line.score))
        return out

    def _latin(self, img, box, text: str):
        eng = self._load_secondary()
        if eng is None:
            return None
        x, y, w, h = box
        pad = 3
        crop = img[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
        if crop.size == 0:
            return None
        try:
            return self._secondary_call(eng, crop, text)
        except Exception:  # noqa: BLE001 - a failed reading keeps the first one
            return None

    def _fix_latin_words(self, img, text: str, words) -> str:
        """Korean line with English in it: read only the English parts again with the Latin
        model (the Korean model turns short words like "UI" into "ü", "CI" into "cI")."""
        for w in words:
            try:
                wtext, wscore, wq = str(w[0]), float(w[1]), np.asarray(w[2], float)
            except (TypeError, ValueError, IndexError):
                continue
            if not _LATIN_LETTER.search(wtext) or wtext not in text:
                continue
            wx, wy = wq[:, 0].min(), wq[:, 1].min()
            ww, wh = wq[:, 0].max() - wx, wq[:, 1].max() - wy
            weights = [_char_weight(ch) for ch in wtext]
            total = sum(weights) or 1.0
            new_word = wtext
            for a, b in reversed(_latin_runs(wtext)):          # right to left: indices stay valid
                part = wtext[a:b]
                left = wx + ww * sum(weights[:a]) / total
                right = wx + ww * sum(weights[:b]) / total
                res = self._latin(img, (int(left), int(wy), max(1, int(round(right - left))), int(round(wh))), part)
                if not res or not str(res[0]).strip() or float(res[1]) < wscore - SECOND_READING_MARGIN - 0.1:
                    continue
                latin = str(res[0]).strip()
                fixed = fix_mixed_line(part, latin)
                if fixed is None and (a, b) == (0, len(wtext)) and not part.isascii() \
                        and not _HANGUL.search(latin) and len(latin) <= 2 * len(part) + 2:
                    fixed = latin                      # a whole short word misread ("UI" -> "ü")
                if fixed:
                    new_word = new_word[:a] + fixed + new_word[b:]
            if new_word != wtext:
                text = text.replace(wtext, new_word, 1)
        return text

    def read_words(self, img: np.ndarray) -> list[tuple[str, tuple]]:
        """Words (Korean: single syllables) with their boxes (x0, y0, x1, y1): for layouts that
        must be cut at exact x positions. English words are read again with the English model."""
        if img is None or img.size == 0:
            return []
        engine = self._load()
        m = MARGIN_LOW if self.margin else 0                 # text at the very edge is found too
        work = with_margin(img, m) if m else np.ascontiguousarray(img)
        try:
            r = engine(work, use_det=True, use_cls=False, use_rec=True, return_word_box=True)
        except TypeError:
            return [(l.text, (l.box[0], l.box[1], l.box[0] + l.box[2], l.box[1] + l.box[3]))
                    for l in self._run_tile(engine, img, 0, 0)]
        out = []
        for line_score, words in zip(getattr(r, "scores", ()) or (), getattr(r, "word_results", ()) or ()):
            for w, ws, q in words or ():
                q = np.asarray(q, float)
                x0, y0 = q[:, 0].min() - m, q[:, 1].min() - m
                x1, y1 = q[:, 0].max() - m, q[:, 1].max() - m
                text = str(w)
                if re.search(r"[A-Za-z][\uac00-\ud7a3][A-Za-z]", text):        # "Gi태ub": a misread inside
                    text = self._fix_latin_words(work, text, [(text, ws, q.tolist())]) or text   # an English word
                elif _ODD_LATIN_BY_HANGUL.search(text):                          # "ç가" for "CI가"
                    text = self._reread_word(engine, work, q) or text
                elif _LATIN_LETTER.search(text) and not _HANGUL.search(text):
                    pad = 3
                    crop = work[max(0, int(y0 + m) - pad):int(y1 + m) + pad, max(0, int(x0 + m) - pad):int(x1 + m) + pad]
                    line = self._second_reading(crop, OcrLine(text, (pad, pad, int(x1 - x0), int(y1 - y0)),
                                                              float(ws) if ws is not None else float(line_score)))
                    text = line.text if "  " not in text or "  " in line.text else text
                    text = fill_dropped_arrows(work, text, (x0 + m, y0 + m, x1 + m, y1 + m))
                if re.search("[←→↔«»⇔⇆]", text) and text.strip() not in ARROWS:     # "«를", "←가": check the shape
                    text = fill_dropped_arrows(work, text.replace("«", "←").replace("»", "→"),
                                               (x0 + m, y0 + m, x1 + m, y1 + m))
                if text.strip() in ARROWS:                        # the reader only knows → and ←
                    if _arrow_in(work, (x0 + m - 4, y0 + m, x1 + m + 4, y1 + m)) == "↔":
                        text = "↔"
                out.append((fix_capital_i(text), (float(x0), float(y0), float(x1), float(y1))))
        return out

    def _reread_word(self, engine, img, q) -> str | None:
        """One word read again on its own, enlarged; kept only if it no longer has odd letters."""
        x0, y0 = int(q[:, 0].min()) - 3, int(q[:, 1].min()) - 3
        x1, y1 = int(q[:, 0].max()) + 4, int(q[:, 1].max()) + 4
        crop = img[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            return None
        if crop.shape[0] < SMALL_LINE_PX:
            k = SMALL_LINE_PX / crop.shape[0]
            crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        crop = with_margin(crop, 8)
        try:
            r = engine(crop, use_det=False, use_cls=False, use_rec=True)
        except Exception:  # noqa: BLE001
            return None
        if r is None or not r.txts:
            return None
        t = str(r.txts[0]).strip()
        return t if t and not _ODD_LATIN_BY_HANGUL.search(t) else None

    def read_line(self, img: np.ndarray) -> str:
        """Text of a crop holding one line (no text finding): table cells cut out exactly."""
        if img is None or img.size == 0:
            return ""
        engine = self._load()
        img = np.ascontiguousarray(img)
        try:
            r = engine(img, use_det=False, use_cls=False, use_rec=True)
        except TypeError:                          # test fakes: whole recognition
            lines = self._run_tile(engine, img, 0, 0)
            return " ".join(l.text for l in lines)
        if r is None or not r.txts or not str(r.txts[0]).strip():
            return ""
        line = OcrLine(str(r.txts[0]), (0, 0, img.shape[1], img.shape[0]), float(r.scores[0]))
        line = self._second_reading(img, line)
        return fix_capital_i(line.text)

    def _join_pieces(self, engine, img, pieces):
        """The text finder sometimes cuts one line into overlapping pieces ("Act as my" | "elite" |
        "academic advisor."); read apart, the edges get read twice ("e elite"). Pieces of one
        row that overlap or touch are read again as one line."""
        pieces = sorted(pieces, key=lambda p: (p[1][1], p[1][0]))
        groups: list[list] = []
        for p in sorted(pieces, key=lambda p: p[1][0]):
            x, y, w, h = p[1]
            for g in groups:
                gx, gy, gw, gh = g[-1][1]
                v = min(y + h, gy + gh) - max(y, gy)
                if v >= 0.6 * min(h, gh) and x <= gx + gw + 2 and x + w > gx + gw:
                    g.append(p)
                    break
            else:
                groups.append([p])
        out = []
        for g in groups:
            if len(g) > 1 and any(_HANGUL.search(p[0]) for p in g):
                out.extend(tuple(p) for p in g)          # Korean lines keep their word boxes
                continue
            if len(g) == 1:
                out.append(tuple(g[0]))
                continue
            x1 = min(p[1][0] for p in g)
            y1 = min(p[1][1] for p in g)
            x2 = max(p[1][0] + p[1][2] for p in g)
            y2 = max(p[1][1] + p[1][3] for p in g)
            box = (x1, y1, x2 - x1, y2 - y1)
            joined = " ".join(p[0] for p in g)
            low = min(p[2] for p in g)
            text, score, words = joined, low, ()
            try:
                crop = np.ascontiguousarray(img[max(0, y1 - 2):y2 + 2, max(0, x1 - 2):x2 + 2])
                r = engine(crop, use_det=False, use_cls=False, use_rec=True, return_word_box=True)
                if r is not None and r.txts and str(r.txts[0]).strip() and float(r.scores[0]) >= low - 0.05:
                    text, score = str(r.txts[0]), float(r.scores[0])
                    wr = getattr(r, "word_results", None)
                    if wr:
                        dx, dy = max(0, x1 - 2), max(0, y1 - 2)
                        words = tuple((wt, ws, (np.asarray(wq, float) + [dx, dy]).tolist()) for wt, ws, wq in wr[0])
            except Exception:  # noqa: BLE001 - engines that can't read a given line: keep the pieces' text
                pass
            out.append((text, box, score, words))
        return out

    def _second_reading(self, img, line: OcrLine) -> OcrLine:
        if not needs_latin(line.text):
            return line
        eng = self._load_secondary()
        if eng is None:
            return line
        x, y, w, h = line.box
        pad = 3
        crop = img[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
        if 0 < crop.shape[0] < SMALL_LINE_PX:          # small print reads better a little bigger
            k = SMALL_LINE_PX / crop.shape[0]
            crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        try:
            res = self._secondary_call(eng, crop, line.text)
        except Exception:  # noqa: BLE001 - a failed second reading keeps the first one
            return line
        if not res or not str(res[0]).strip():
            return line
        text, score = res
        if score >= line.score - SECOND_READING_MARGIN:
            return OcrLine(text, line.box, score)
        return line


TILE_H = 1900            # tile height (rows); stays under the recognizer's 2000 px shrink limit
TILE_W = 3800            # tile width (Global.max_side_len is raised to 4000 for wide screens)
TILE_OVERLAP = 220       # >= the tallest text line, so every line is whole in the tile owning it


def _starts(total: int, size: int) -> list[int]:
    if total <= size:
        return [0]
    step = size - TILE_OVERLAP
    starts = list(range(0, total - size, step))
    starts.append(total - size)
    return starts


def tiles(w: int, h: int) -> list[tuple[int, int, int, int]]:
    """(x, y, w, h) tiles covering the image, overlapping by at least TILE_OVERLAP."""
    tw, th = min(w, TILE_W), min(h, TILE_H)
    return [(x, y, tw, th) for y in _starts(h, th) for x in _starts(w, tw)]


def _bounds(starts: list[int], size: int, total: int) -> list[tuple[float, float]]:
    """Per tile, the span whose line centres it reports: up to the middle of each overlap."""
    out = []
    for i, s in enumerate(starts):
        lo = 0 if i == 0 else (starts[i - 1] + size + s) / 2
        hi = total + 1 if i == len(starts) - 1 else (s + size + starts[i + 1]) / 2
        out.append((lo, hi))
    return out


def _owned(x0, y0, tw, th, w, h) -> tuple[float, float, float, float]:
    xs, ys = _starts(w, tw), _starts(h, th)
    (xl, xh), (yl, yh) = _bounds(xs, tw, w)[xs.index(x0)], _bounds(ys, th, h)[ys.index(y0)]
    return xl, yl, xh, yh


INK_PAD = 24             # px of paper kept around the ink of a tile
MIN_SIDE = 736           # the detector enlarges anything smaller; keep tiles at least this big


def _ink_box(tile: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the part of a tile that has any detail, padded; None if it is blank."""
    g = tile[..., :3].max(axis=2).astype(np.int16) if tile.ndim == 3 else tile.astype(np.int16)
    lo = tile[..., :3].min(axis=2).astype(np.int16) if tile.ndim == 3 else g
    rows = (g.max(axis=1) - lo.min(axis=1)) > 24
    if not rows.any():
        return None
    cols = (g.max(axis=0) - lo.min(axis=0)) > 24
    h, w = rows.shape[0], cols.shape[0]

    def span(mask, size):
        idx = np.nonzero(mask)[0]
        a, b = max(0, int(idx[0]) - INK_PAD), min(size, int(idx[-1]) + 1 + INK_PAD)
        need = min(size, MIN_SIDE)
        if b - a < need:                       # grow around the ink, inside the tile
            extra = need - (b - a)
            a = max(0, a - extra // 2)
            b = min(size, a + need)
            a = max(0, b - need)
        return a, b
    y0, y1 = span(rows, h)
    x0, x1 = span(cols, w)
    return x0, y0, x1 - x0, y1 - y0


def reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Top-to-bottom rows (tolerating small vertical offsets), left-to-right inside a row."""
    rows: list[list[OcrLine]] = []
    for l in sorted(lines, key=lambda l: l.box[1] + l.box[3] / 2):
        cy = l.box[1] + l.box[3] / 2
        if rows:
            last = rows[-1][0]
            if abs(cy - (last.box[1] + last.box[3] / 2)) <= max(last.box[3], l.box[3]) * 0.5:
                rows[-1].append(l)
                continue
        rows.append([l])
    return [l for row in rows for l in sorted(row, key=lambda l: l.box[0])]


def select_text(lines: list[OcrLine], rect: tuple) -> str:
    """Text under a dragged rectangle (x, y, w, h): whole characters whose horizontal half lies
    inside it (widths estimated proportionally), rows joined by newlines, segments by spaces."""
    rx, ry, rw, rh = rect
    picked: list[OcrLine] = []
    for l in reading_order(lines):
        x, y, w, h = l.box
        if y + h <= ry or y >= ry + rh or x + w <= rx or x >= rx + rw or not l.text:
            continue
        per = w / len(l.text)
        chars = [c for i, c in enumerate(l.text) if rx <= x + (i + 0.5) * per <= rx + rw]
        part = "".join(chars).strip()
        if part:
            picked.append(OcrLine(part, l.box, l.score))
    return _join_rows(picked)


def _join_rows(lines: list[OcrLine]) -> str:
    """Segments in reading order: the ones on one visual row joined by spaces, rows by newlines."""
    rows: list[list[OcrLine]] = []
    for l in lines:
        cy = l.box[1] + l.box[3] / 2
        if rows and abs(cy - (rows[-1][0].box[1] + rows[-1][0].box[3] / 2)) <= max(l.box[3], rows[-1][0].box[3]) * 0.5:
            rows[-1].append(l)
        else:
            rows.append([l])
    return "\n".join(" ".join(l.text for l in row) for row in rows)


def full_text(lines: list[OcrLine]) -> str:
    """All recognized text. Words the detector split apart on one row go back on one line."""
    return _join_rows([l for l in reading_order(lines) if l.text])
