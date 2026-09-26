"""Offline OCR (RapidOCR + ONNX, Korean PP-OCRv5). Loaded lazily, warmed up in the
background at startup so the first recognition does not wait for model loading."""
from __future__ import annotations

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


class OcrEngine:
    def __init__(self, factory: Callable | None = None):
        self._factory = factory or default_factory
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

    def warmup(self) -> threading.Thread:
        def run():
            try:
                self._load()
            except OcrUnavailable:
                pass
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
            lines.append(OcrLine(str(text), box, float(score)))
        return reading_order(lines)


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
