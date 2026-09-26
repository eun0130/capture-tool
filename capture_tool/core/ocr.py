"""Offline OCR (RapidOCR + ONNX, Korean PP-OCRv5). Loaded lazily, warmed up in the
background at startup so the first recognition does not wait for model loading."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
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


def default_factory():
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    return RapidOCR(params={
        "Global.log_level": "error",
        "Global.use_cls": False,  # screenshots are upright; the classifier flips digit lines
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.KOREAN,  # Korean dictionary also covers Latin letters/digits
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
    })


def latin_factory():
    """Recognizer for Latin-script languages (French, Spanish, German, Italian, Portuguese, ...).
    The Korean dictionary lacks accented letters (ç, é, ñ, ß, ¿ ...)."""
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    return RapidOCR(params={
        "Global.log_level": "error",
        "Global.use_cls": False,
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Rec.lang_type": LangRec.LATIN,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
    })


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
        def run():
            try:
                self._load()
            except OcrUnavailable:
                pass
            self._load_secondary()
        t = threading.Thread(target=run, name="ocr-warmup", daemon=True)
        t.start()
        return t

    def recognize(self, img: np.ndarray | None) -> list[OcrLine]:
        if img is None or img.size == 0 or min(img.shape[:2]) < 4:
            return []
        engine = self._load()
        r = engine(img)
        if r is None or r.txts is None or r.boxes is None:
            return []
        lines = []
        for quad, text, score in zip(r.boxes, r.txts, r.scores):
            if float(score) < MIN_SCORE or not str(text).strip():
                continue
            q = np.asarray(quad, float)
            x, y = q[:, 0].min(), q[:, 1].min()
            box = (int(round(x)), int(round(y)), int(round(q[:, 0].max() - x)), int(round(q[:, 1].max() - y)))
            lines.append(self._second_reading(img, OcrLine(str(text), box, float(score))))
        return reading_order(lines)

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


def full_text(lines: list[OcrLine]) -> str:
    return "\n".join(l.text for l in lines)
