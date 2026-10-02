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
LATIN_MODELS = ["latin_PP-OCRv5_rec_mobile.onnx"]
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
        "Rec.lang_type": LangRec.KOREAN if lang == "korean" else LangRec.LATIN,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
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
SECOND_READING_MARGIN = 0.05  # prefer the Latin reading unless clearly less confident


def needs_latin(text: str) -> bool:
    return not _HANGUL.search(text) and bool(_LATIN_LETTER.search(text))


class OcrEngine:
    def __init__(self, factory: Callable | None = None, secondary_factory: Callable | None = None,
                 secondary_call: Callable | None = None):
        self._factory = factory or default_factory
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
                tile_lines = self._run_tile(engine, img[y0 + iy:y0 + iy + ih, x0 + ix:x0 + ix + iw], x0 + ix, y0 + iy)
            else:
                tile_lines = self._run_tile(engine, img[y0:y0 + th, x0:x0 + tw], x0, y0)
            for line in tile_lines:
                bx, by, bw, bh = line.box
                cx, cy = bx + bw / 2, by + bh / 2
                if own[0] <= cx < own[2] and own[1] <= cy < own[3]:
                    lines.append(line)
        return reading_order(lines)

    def _run_tile(self, engine, img: np.ndarray, x0: int, y0: int) -> list[OcrLine]:
        r = engine(np.ascontiguousarray(img) if not img.flags["C_CONTIGUOUS"] else img)
        if r is None or r.txts is None or r.boxes is None:
            return []
        out = []
        for quad, text, score in zip(r.boxes, r.txts, r.scores):
            if float(score) < MIN_SCORE or not str(text).strip():
                continue
            q = np.asarray(quad, float)
            x, y = q[:, 0].min(), q[:, 1].min()
            box = (int(round(x)), int(round(y)), int(round(q[:, 0].max() - x)), int(round(q[:, 1].max() - y)))
            line = self._second_reading(img, OcrLine(str(text), box, float(score)))
            bx, by, bw, bh = line.box
            out.append(OcrLine(line.text, (bx + x0, by + y0, bw, bh), line.score))
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
