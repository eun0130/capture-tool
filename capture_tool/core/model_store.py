"""AI model packs (offline translation, offline summary): catalog pinned to exact files and
SHA-256 hashes, download with verification, safe unzip and an install marker.

Where packs live: the app folder (packs shipped in the installer) or
%LOCALAPPDATA%\\CaptureTool\\models (downloaded on first use)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MARKER = ".installed.json"
CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelFile:
    url: str
    sha256: str
    size: int
    name: str
    unzip: bool = False


@dataclass(frozen=True)
class Pack:
    id: str
    title: str
    kind: str                      # "mt" (translation pair) or "llm" (summary model)
    files: tuple


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def mt_pack_id(src: str, tgt: str) -> str:
    return f"mt-{src}_{tgt}"


LLM_PACK = "llm-qwen3-1.7b"
_ARGOS = "https://argos-net.com/v1/translate-{}.argosmodel"
_HF = "https://huggingface.co/hb-dev/Qwen3-1.7B-ONNX-GenAI/resolve/f9a79b179d34383b3e6afc95ae4882767067ba31/{}"
# (pair, version, size, sha256) — Argos Translate packages (OPUS data, MIT/CC-BY), pinned by hash
_MT = [
    ("ko_en", "1_1", 118852077, "6da8f3db6ca40f42b1875570a1c06856f6e17c7ef62845d85de217ba548c1471"),
    ("en_ko", "1_1", 120789009, "e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc"),
    ("ja_en", "1_1", 117155716, "623e3477959a815eb0a5ef53e09079ae8f1f9d3bbcd230473baf28c03fb83335"),
    ("en_ja", "1_1", 120470284, "16300cc4eaa85320520cabcf433b63d01be40ef6966251de72043a083408f716"),
    ("zh_en", "1_9", 74481402, "62e7af5a3a48b530e47b7b3e5c78c2de79073ecd815750d2bf3ab35b4a67da2d"),
    ("en_zh", "1_9", 70743021, "433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab"),
    ("fr_en", "1_9", 66585033, "3b3052fee6bb1e8e8e632a26a723eb2a2c7710dfe73ba61ffd9b83e85d4f14c1"),
    ("en_fr", "1_9", 65472327, "3a65ed83364f4e7b06e30f9dd823db1934899ed3ce839e63f46dc7b09dc797b4"),
    ("es_en", "1_9", 285208831, "c54df2b62fceaf54a3ce5d97db6bf56efd7940063329f6778f4212d2acb370d4"),
    ("en_es", "1_0", 87503191, "d698d0ef87ad70d5d184b7fa6965905bf4368f09a2bb9ffb165a79bac96af0c4"),
    ("de_en", "1_3", 150512831, "becc2b0011f8249fcb89be9ecb75ba0d876b1fab93c28ee6ff0420936897d637"),
    ("en_de", "1_3", 150508297, "6cd847f0c06c9c66013e6b0932e07fd54a6d90894659c02bf6c5247b72fb25b1"),
]
# Qwen3-1.7B (Apache-2.0) converted for onnxruntime-genai, pinned to one revision
_LLM = [
    ("genai_config.json", 1520, "d328d2ad4cbd7915eee3ad047eabfc562d8daf7307b202c1e6aaef4e8a236ba2"),
    ("config.json", 8697, "14c4e163fc54e5c7301a7f26054386ac77734401355fecd530ce4a98233f070c"),
    ("chat_template.jinja", 4168, "a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8"),
    ("tokenizer_config.json", 663, "bfd13b57b2e0c2cb582f311c0895f077d16a868c0dc61e4dbbba544a835341d6"),
    ("tokenizer.json", 11422648, "979d160e081df25a1bf7f4e2e8f4c441b5dfdc9a8e84aec9f32e80445e1b59b8"),
    ("model.onnx", 1408943689, "9fddc5a0a7f9c51132c376db8fe44774b17a8e42d721c4d289ade16af87da0bd"),
]
_NAMES = {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "fr": "프랑스어", "es": "스페인어", "de": "독일어"}


def _catalog() -> dict[str, Pack]:
    out: dict[str, Pack] = {}
    for pair, ver, size, sha in _MT:
        src, tgt = pair.split("_")
        f = ModelFile(_ARGOS.format(f"{pair}-{ver}"), sha, size, f"{pair}.zip", unzip=True)
        out[mt_pack_id(src, tgt)] = Pack(mt_pack_id(src, tgt), f"번역 {_NAMES[src]}→{_NAMES[tgt]}", "mt", (f,))
    files = tuple(ModelFile(_HF.format(name), sha, size, name) for name, size, sha in _LLM)
    out[LLM_PACK] = Pack(LLM_PACK, "오프라인 요약 모델 (Qwen3 1.7B)", "llm", files)
    return out


CATALOG = _catalog()


def user_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "CaptureTool" / "models"


def bundled_root() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "ai_models"


def roots() -> list[Path]:
    return [bundled_root(), user_root()]


def pack_size(pack: Pack) -> int:
    return sum(f.size for f in pack.files)


def installed_dir(pack: Pack, search: list[Path] | None = None) -> Path | None:
    for root in search if search is not None else roots():
        d = Path(root) / pack.id
        try:
            data = json.loads((d / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("files") == [f.sha256 for f in pack.files]:
            return d
    return None


def free_bytes(path: Path) -> int:
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def _urlopen(url: str, timeout: float = 30):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "CaptureTool"})
    return urllib.request.urlopen(req, timeout=timeout)   # https only (catalog), certificate checked


def _safe_extract(zpath: Path, dest: Path) -> None:
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise DownloadError("모델 파일이 올바르지 않습니다 (압축 파일 경로 오류).")
        z.extractall(dest)


def _remove(path: Path) -> None:
    """Remove this app's own partial download (never anything else)."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            pass


def download(pack: Pack, root: Path, fetch: Callable | None = None,
             progress: Callable[[int, int], None] | None = None,
             cancel: Callable[[], bool] | None = None) -> Path:
    """Download, verify and install `pack` under root/pack.id. Returns that folder."""
    fetch = fetch or _urlopen
    cancel = cancel or (lambda: False)
    root = Path(root)
    total = pack_size(pack)
    need = total * 2 if any(f.unzip for f in pack.files) else total
    root.mkdir(parents=True, exist_ok=True)
    if free_bytes(root) < need + (50 << 20) and free_bytes(root) < need:
        raise DownloadError(f"디스크 공간이 부족합니다. {need / 2**30:.1f}GB 이상 비워 주세요.")
    final = root / pack.id
    stage = root / f"{pack.id}.staging"
    _remove(stage)
    stage.mkdir(parents=True)
    done = 0
    try:
        for f in pack.files:
            part = stage / (f.name + ".part")
            h = hashlib.sha256()
            try:
                resp = fetch(f.url, timeout=30)
            except OSError as e:
                raise DownloadError(f"모델을 받지 못했습니다. 인터넷 연결을 확인해 주세요. ({e})") from e
            with resp, open(part, "wb") as out:
                while True:
                    if cancel():
                        raise Cancelled()
                    try:
                        block = resp.read(CHUNK)
                    except OSError as e:
                        raise DownloadError(f"받는 중 인터넷 연결이 끊겼습니다. ({e})") from e
                    if not block:
                        break
                    out.write(block)
                    h.update(block)
                    done += len(block)
                    if progress:
                        progress(min(done, total), total)
            if h.hexdigest() != f.sha256:
                raise DownloadError("받은 파일이 손상되었거나 다른 파일입니다. 다시 시도해 주세요.")
            target = stage / f.name
            part.replace(target)
            if f.unzip:
                try:
                    _safe_extract(target, stage)
                except zipfile.BadZipFile as e:
                    raise DownloadError("받은 파일이 손상되었습니다.") from e
                _remove(target)
        (stage / MARKER).write_text(json.dumps({"files": [f.sha256 for f in pack.files]}), encoding="utf-8")
        _remove(final)
        stage.replace(final)
        return final
    except BaseException:
        _remove(stage)
        raise


def mt_files(pack_dir: Path) -> tuple[Path, Path]:
    """(CTranslate2 model folder, tokenizer file) inside an Argos pack. The tokenizer is
    sentencepiece.model, or bpe.model (Moses + BPE) in some newer packs."""
    for bin_ in Path(pack_dir).rglob("model.bin"):
        model_dir = bin_.parent
        for name in ("sentencepiece.model", "bpe.model"):
            tok = model_dir.parent / name
            if tok.exists():
                return model_dir, tok
    raise FileNotFoundError(f"translation model files missing in {pack_dir}")
