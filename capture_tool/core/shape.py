"""Shape search behind 캡처 찾기 (v0.9.1): a CLIP ViT-B/32 picture encoder and the multilingual text
encoder aligned to it (DistilBERT -> mean pooling -> dense 768->512), both int8 ONNX files of the
optional "clip-vit-b32-ml" model pack. A Korean or English phrase and a picture land in the same
512-dimensional space, so their cosine says how much the picture looks like the words. Raw CLIP
scores suffer from "hubs" (one bland picture is close to every phrase): both sides are centred -
a phrase vector minus the mean of a fixed bank of phrases, a picture vector minus the mean of
the catalogue's pictures (see Catalog.nearest). Qt-free; the ONNX sessions are injected (tests
use fakes)."""
from __future__ import annotations

import json
import os
import struct
import threading
import unicodedata
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import model_store as ms

DIM = 512
MAX_TOKENS = 128             # the text encoder was trained with this sequence length
SIDE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
MIN_SCORE = 0.08             # words -> picture (centred scores): below this nothing looks like the words
SAME_SCORE = 0.75            # picture -> picture (raw cosine): above this they show the same thing
MIN_CENTRE = 8               # pictures needed before their mean is worth subtracting
# the phrase bank whose mean is the "modality centre" of the text encoder (what every phrase shares)
BANK = ["표", "그래프", "설정 창", "대화 상자", "소스 코드", "사진", "지도", "웹 페이지", "메뉴", "채팅", "문서", "로그인 화면",
        "아이콘", "버튼", "글자", "파일 목록", "달력", "이메일", "동영상", "검은 바탕", "흰 바탕", "a screenshot", "a photo",
        "text", "a window"]
THREADS = max(1, min(4, (os.cpu_count() or 4) // 2))


class ModelMissing(Exception):
    def __init__(self, packs: list[str]):
        super().__init__("model packs missing: " + ", ".join(packs))
        self.packs = packs


# --- words -> token ids ------------------------------------------------------------------------------
def _is_punct(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_ideograph(cp: int) -> bool:
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF or 0x2A700 <= cp <= 0x2B73F
            or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF or 0xF900 <= cp <= 0xFAFF
            or 0x2F800 <= cp <= 0x2FA1F)


class WordPiece:
    """BERT's basic tokenizer (cased, ideographs one by one, punctuation apart) + WordPiece."""

    def __init__(self, vocab: dict[str, int]):
        self.vocab = vocab
        self.cls, self.sep, self.unk = vocab["[CLS]"], vocab["[SEP]"], vocab["[UNK]"]

    @classmethod
    def from_file(cls, path: Path) -> "WordPiece":
        words = Path(path).read_text(encoding="utf-8").split("\n")
        return cls({w: i for i, w in enumerate(words) if w})

    @staticmethod
    def _words(text: str) -> list[str]:
        out = []
        for ch in unicodedata.normalize("NFC", text):
            cp = ord(ch)
            if ch.isspace():
                out.append(" ")
            elif cp in (0, 0xFFFD) or unicodedata.category(ch).startswith("C"):
                continue
            elif _is_ideograph(cp) or _is_punct(ch):
                out.append(" " + ch + " ")
            else:
                out.append(ch)
        return "".join(out).split()

    def _pieces(self, word: str) -> list[str]:
        if len(word) > 100:
            return ["[UNK]"]
        pieces, start = [], 0
        while start < len(word):
            end, cur = len(word), None
            while start < end:
                sub = ("##" if start else "") + word[start:end]
                if sub in self.vocab:
                    cur = sub
                    break
                end -= 1
            if cur is None:
                return ["[UNK]"]
            pieces.append(cur)
            start = end
        return pieces

    def tokens(self, text: str) -> list[str]:
        out: list[str] = []
        for w in self._words(text):
            out.extend(self._pieces(w))
        return out

    def ids(self, text: str, max_len: int = MAX_TOKENS) -> list[int]:
        body = [self.vocab[t] for t in self.tokens(text)][:max_len - 2]
        return [self.cls] + body + [self.sep]


# --- picture -> tensor --------------------------------------------------------------------------------
def preprocess(img: np.ndarray) -> np.ndarray:
    """BGR picture -> 1x3x224x224 float32 the way CLIP was trained: short side to 224, centre crop,
    RGB, mean/std."""
    h, w = img.shape[:2]
    s = SIDE / min(h, w)
    nw, nh = max(SIDE, round(w * s)), max(SIDE, round(h * s))
    small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y, x = (nh - SIDE) // 2, (nw - SIDE) // 2
    crop = small[y:y + SIDE, x:x + SIDE, :3][:, :, ::-1].astype(np.float32) / 255.0
    crop = (crop - MEAN) / STD
    return np.ascontiguousarray(crop.transpose(2, 0, 1)[None])


def load_safetensors(path: Path) -> dict[str, np.ndarray]:
    """The dense layer's weights (no torch: the format is a JSON header + raw tensors)."""
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
        data = f.read()
    kinds = {"F32": np.float32, "F16": np.float16, "F64": np.float64, "I64": np.int64}
    out = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        a, b = info["data_offsets"]
        out[name] = np.frombuffer(data[a:b], dtype=kinds[info["dtype"]]).reshape(info["shape"])
    return out


def _session(path: Path, threads: int):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.log_severity_level = 3
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


class ClipModel:
    def __init__(self, pack_dir: Path, session: Callable | None = None, threads: int = THREADS):
        vision, text, vocab, dense = ms.clip_files(pack_dir)
        make = session or _session
        self.vision = make(vision, threads)
        self.text = make(text, threads)
        self.tok = WordPiece.from_file(vocab)
        w = next(iter(load_safetensors(dense).values()))
        self.dense = np.ascontiguousarray(w.astype(np.float32).T)         # (768, 512)
        self._centre: np.ndarray | None = None

    @staticmethod
    def _unit(v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, np.float32).reshape(-1)
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    def embed_image(self, img: np.ndarray) -> np.ndarray:
        out = self.vision.run(None, {"pixel_values": preprocess(img)})[0]
        return self._unit(out[0])

    def _raw_text(self, text: str) -> np.ndarray:
        ids = np.array([self.tok.ids(text)], np.int64)
        hidden = self.text.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0][0]
        pooled = np.asarray(hidden, np.float32).mean(axis=0)
        return self._unit(pooled @ self.dense)

    def text_centre(self) -> np.ndarray:
        if self._centre is None:
            self._centre = np.mean([self._raw_text(p) for p in BANK], axis=0).astype(np.float32)
        return self._centre

    def embed_text(self, text: str, centre: bool = True) -> np.ndarray:
        """The phrase's vector; centred (the bank's mean subtracted) unless asked raw."""
        v = self._raw_text(text)
        return self._unit(v - self.text_centre()) if centre else v


# --- storing a vector ---------------------------------------------------------------------------------
def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, np.float32).astype(np.float16).tobytes()


def from_blob(blob) -> np.ndarray | None:
    if not blob or len(blob) != DIM * 2:
        return None
    return np.frombuffer(bytes(blob), dtype=np.float16).astype(np.float32)


# --- the service the app talks to ---------------------------------------------------------------------
def find_clip() -> Path | None:
    return ms.installed_dir(ms.CATALOG[ms.CLIP_PACK])


class ShapeSearch:
    """Loads the pack on first use (a few hundred ms, under a lock), answers vectors, unloads when
    the app has been idle."""

    def __init__(self, find: Callable[[], Path | None] | None = None, loader: Callable | None = None,
                 threads: int = THREADS):
        self.find = find or find_clip
        self.loader = loader or (lambda d: ClipModel(d, threads=threads))
        self._model: ClipModel | None = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return self.find() is not None

    def missing(self) -> list[str]:
        return [] if self.available() else [ms.CLIP_PACK]

    def loaded(self) -> bool:
        return self._model is not None

    def _get(self) -> ClipModel:
        with self._lock:
            if self._model is None:
                d = self.find()
                if d is None:
                    raise ModelMissing([ms.CLIP_PACK])
                self._model = self.loader(d)
            return self._model

    def text_vector(self, text: str, centre: bool = True) -> np.ndarray:
        return self._get().embed_text(text, centre)

    def image_vector(self, img: np.ndarray) -> np.ndarray:
        return self._get().embed_image(img)

    def image_blob(self, img: np.ndarray) -> bytes:
        return to_blob(self.image_vector(img))

    def unload(self) -> None:
        with self._lock:
            self._model = None
