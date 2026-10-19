"""Shape search core (v0.9.1): the WordPiece tokenizer, CLIP picture preprocessing, the safetensors
reader, the model wrapper over fake ONNX sessions, the embedding blob and ShapeSearch's lazy load.
No real model here (tests/test_shape_real.py measures the real pack when it is installed)."""
import json
import struct
import threading

import numpy as np
import pytest

from capture_tool.core import shape
from capture_tool.core import model_store as ms

VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "a", "bar", "chart", "##s", "표", "그", "##래", "##프", "中", "国", ",", "!", "Excel", "excel"]


def write_safetensors(path, arrays: dict):
    header, blobs, offset = {}, [], 0
    for name, arr in arrays.items():
        raw = np.ascontiguousarray(arr).tobytes()
        header[name] = {"dtype": {"float32": "F32", "float16": "F16"}[str(arr.dtype)], "shape": list(arr.shape),
                        "data_offsets": [offset, offset + len(raw)]}
        blobs.append(raw)
        offset += len(raw)
    h = json.dumps(header).encode()
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(h)) + h + b"".join(blobs))


@pytest.fixture
def vocab():
    return shape.WordPiece({w: i for i, w in enumerate(VOCAB)})


def test_CLIP_01_wordpiece_splits_like_bert(vocab):
    assert vocab.tokens("a bar charts") == ["a", "bar", "chart", "##s"]
    assert vocab.tokens("그래프 표") == ["그", "##래", "##프", "표"]
    assert vocab.tokens("中国") == ["中", "国"]                         # ideographs one by one
    assert vocab.tokens("bar, chart!") == ["bar", ",", "chart", "!"]  # punctuation apart
    assert vocab.tokens("Excel excel") == ["Excel", "excel"]          # cased, as the model was trained
    assert vocab.tokens("zzz") == ["[UNK]"]                             # whole word unknown
    assert vocab.tokens("  a\tbar\n") == ["a", "bar"]
    ids = vocab.ids("a bar")
    assert ids == [2, 4, 5, 3]                                          # [CLS] ... [SEP]
    assert len(vocab.ids(" ".join(["bar"] * 300))) == shape.MAX_TOKENS and vocab.ids("bar" * 1)[-1] == 3


def test_CLIP_02_preprocess_resizes_the_short_side_and_crops_the_middle():
    img = np.zeros((300, 900, 3), np.uint8)
    img[:, 300:600] = 255                                               # a white middle third
    img[:, :300] = (255, 0, 0)                                          # blue (BGR) left third
    x = shape.preprocess(img)
    assert x.shape == (1, 3, 224, 224) and x.dtype == np.float32
    white = (1 - shape.MEAN) / shape.STD
    assert np.allclose(x[0, :, 112, 112], white, atol=1e-5)             # centre crop keeps the middle only
    assert np.allclose(x[0, :, 5, 5], white, atol=1e-5)
    tiny = shape.preprocess(np.full((20, 50, 3), 128, np.uint8))         # upscaled, never an error
    assert tiny.shape == (1, 3, 224, 224)


def test_CLIP_03_safetensors_are_read_with_numpy_only(tmp_path):
    w = np.arange(12, dtype=np.float32).reshape(3, 4)
    h = np.array([1.5, -2], np.float16)
    write_safetensors(tmp_path / "d.safetensors", {"linear.weight": w, "h": h})
    out = shape.load_safetensors(tmp_path / "d.safetensors")
    assert np.array_equal(out["linear.weight"], w) and out["h"].dtype == np.float16 and out["h"].tolist() == [1.5, -2]


class FakeSession:
    """Picture: embeds = per-channel means padded to 512. Text: hidden = one row per token, row =
    token id at column id (so the mean is the ids' histogram / n)."""
    def __init__(self, path):
        self.path = str(path)
        self.fed = []

    def run(self, _, feed):
        self.fed.append({k: v.copy() for k, v in feed.items()})
        if "pixel_values" in feed:
            px = feed["pixel_values"]
            out = np.zeros((px.shape[0], 512), np.float32)
            out[:, :3] = px.mean(axis=(2, 3))
            out[:, 3] = 1.0
            return [out]
        ids, mask = feed["input_ids"], feed["attention_mask"]
        hidden = np.zeros((ids.shape[0], ids.shape[1], 768), np.float32)
        for b in range(ids.shape[0]):
            for t in range(ids.shape[1]):
                hidden[b, t, int(ids[b, t])] = 1.0
        assert mask.shape == ids.shape and mask.dtype == np.int64 and mask.all()
        return [hidden]


@pytest.fixture
def pack(tmp_path):
    d = tmp_path / ms.CLIP_PACK
    d.mkdir()
    (d / "vision.onnx").write_bytes(b"v")
    (d / "text.onnx").write_bytes(b"t")
    (d / "vocab.txt").write_text("\n".join(VOCAB), encoding="utf-8")
    w = np.zeros((512, 768), np.float32)
    for i in range(len(VOCAB)):
        w[i, i] = 1.0                                                   # dense = identity on the first rows
    write_safetensors(d / "dense.safetensors", {"linear.weight": w})
    (d / ms.MARKER).write_text(json.dumps({"files": [f.sha256 for f in ms.CATALOG[ms.CLIP_PACK].files]}))
    return d


def test_CLIP_04_the_model_embeds_pictures_and_words_as_unit_vectors(pack):
    sessions = {}

    def make(path, threads):
        sessions[path.name] = s = FakeSession(path)
        return s
    m = shape.ClipModel(pack, session=make)
    v = m.embed_image(np.full((50, 80, 3), 255, np.uint8))
    assert v.shape == (512,) and v.dtype == np.float32 and abs(np.linalg.norm(v) - 1) < 1e-5
    assert sessions["vision.onnx"].fed[0]["pixel_values"].shape == (1, 3, 224, 224)
    t = m.embed_text("a bar chart", centre=False)
    assert abs(np.linalg.norm(t) - 1) < 1e-5
    ids = sessions["text.onnx"].fed[0]["input_ids"]
    assert ids.tolist() == [[2, 4, 5, 6, 3]] and ids.dtype == np.int64
    expect = np.zeros(512, np.float32)
    for i in (2, 4, 5, 6, 3):
        expect[i] = 1 / 5                                               # mean pooling, then the identity dense
    assert np.allclose(t, expect / np.linalg.norm(expect), atol=1e-6)
    assert len(sessions["text.onnx"].fed) == 1
    assert m.embed_text("", centre=False).shape == (512,)                # empty words: still a vector, no crash
    c = m.embed_text("a bar chart")                                     # centred: the bank's mean taken out
    assert abs(np.linalg.norm(c) - 1) < 1e-5 and not np.allclose(c, t)
    assert m.text_centre() is m.text_centre() and len(sessions["text.onnx"].fed) == 3 + len(shape.BANK)
    assert np.allclose(m.embed_text("a bar chart"), c)                  # the bank is embedded once


def test_CLIP_05_blob_round_trip_is_float16():
    v = np.random.default_rng(1).standard_normal(512).astype(np.float32)
    v /= np.linalg.norm(v)
    b = shape.to_blob(v)
    assert len(b) == 1024 and isinstance(b, bytes)
    back = shape.from_blob(b)
    assert back.dtype == np.float32 and np.abs(back - v).max() < 2e-3
    assert shape.from_blob(b"") is None and shape.from_blob(None) is None and shape.from_blob(b"\x00" * 10) is None


def test_CLIP_06_shape_search_loads_once_lazily_and_unloads(pack, tmp_path):
    found = {"dir": None}
    loads = []

    def loader(d):
        loads.append(d)
        return shape.ClipModel(d, session=lambda p, threads: FakeSession(p))
    s = shape.ShapeSearch(find=lambda: found["dir"], loader=loader)
    assert not s.available() and s.missing() == [ms.CLIP_PACK]
    with pytest.raises(shape.ModelMissing):
        s.text_vector("표")
    found["dir"] = pack
    assert s.available() and s.missing() == [] and loads == []           # nothing loaded until asked
    results = []
    threads = [threading.Thread(target=lambda: results.append(s.text_vector("a bar"))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(loads) == 1 and len(results) == 4                        # one load under the lock
    assert s.image_blob(np.zeros((10, 10, 3), np.uint8)) and len(s.image_blob(np.zeros((10, 10, 3), np.uint8))) == 1024
    assert s.image_vector(np.zeros((10, 10, 3), np.uint8)).shape == (512,)
    s.unload()
    s.text_vector("a")
    assert len(loads) == 2
