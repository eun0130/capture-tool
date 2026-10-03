"""Offline AI: translation (CTranslate2 + SentencePiece, Argos packs) and summary
(onnxruntime-genai, Qwen3 1.7B). Models load on first use; unload() frees their memory."""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Callable

from . import model_store as ms
from .ai_text import (chunk_text, clean_summary, dedupe_text, restore_layout, route, split_for_mt,
                      summary_prompt, summary_should_stop)

BATCH = 16                # sentences per translation call (bounded memory, lets cancel act)
SUMMARY_CHUNK = 2500      # characters per summary pass
SUMMARY_TOKENS = 256      # new tokens per summary (3-5 bullets need ~80-180)
THREADS = 4               # translation: 4 measured faster than 8 (small model, short sentences)


def llm_threads(cores: int | None) -> int:
    """Half the cores, at most 8: reading the text (prefill) scales with threads - 4 -> 8 made a
    long summary 33% faster - while half the PC stays free."""
    return max(1, min(8, (cores or 4) // 2))


LLM_THREADS = llm_threads(os.cpu_count())


class ModelMissing(Exception):
    def __init__(self, packs: list[str]):
        super().__init__("모델이 필요합니다: " + ", ".join(packs))
        self.packs = packs


class Cancelled(Exception):
    pass


class Busy(Exception):
    pass


def strip_think(text: str) -> str:
    """Qwen3 may emit an (empty) <think> block before the answer."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


# --- translation ----------------------------------------------------------------------------------
class _SentencePiece:
    def __init__(self, path):
        import sentencepiece as spm
        self.sp = spm.SentencePieceProcessor(model_file=str(path))

    def encode(self, text: str) -> list[str]:
        return self.sp.encode(text, out_type=str)

    def decode(self, tokens: list[str]) -> str:
        return self.sp.decode(tokens)


class _MosesBPE:
    """Some newer Argos packs (es->en) use Moses tokenization + BPE instead of SentencePiece."""

    def __init__(self, path, src: str, tgt: str):
        from sacremoses import MosesDetokenizer, MosesPunctNormalizer, MosesTokenizer
        from subword_nmt.apply_bpe import BPE
        self.norm, self.tok, self.detok = MosesPunctNormalizer(src), MosesTokenizer(src), MosesDetokenizer(tgt)
        with open(path, encoding="utf-8") as f:
            self.bpe = BPE(f)

    def encode(self, text: str) -> list[str]:
        words = " ".join(self.tok.tokenize(self.norm.normalize(text), escape=False)).split(" ")
        return self.bpe.segment_tokens([w for w in words if w])

    def decode(self, tokens: list[str]) -> str:
        return self.detok.detokenize(" ".join(tokens).replace("@@ ", "").split(" "))


class _CT2Pair:
    def __init__(self, pack_dir, threads: int = THREADS):
        import ctranslate2
        model_dir, tok_file = ms.mt_files(pack_dir)
        self.tr = ctranslate2.Translator(str(model_dir), device="cpu", inter_threads=1, intra_threads=threads)
        if tok_file.name == "bpe.model":
            meta = json.loads((tok_file.parent / "metadata.json").read_text(encoding="utf-8"))
            self.tok = _MosesBPE(tok_file, meta["from_code"], meta["to_code"])
        else:
            self.tok = _SentencePiece(tok_file)

    def translate_batch(self, pieces: list[str]) -> list[str]:
        toks = [self.tok.encode(p) for p in pieces]
        res = self.tr.translate_batch(toks, beam_size=2, max_decoding_length=512)
        return [self.tok.decode(r.hypotheses[0]) for r in res]


def _find_pair(pair: str):
    src, tgt = pair.split("_")
    pack = ms.CATALOG.get(ms.mt_pack_id(src, tgt))
    return ms.installed_dir(pack) if pack else None


class LocalTranslator:
    def __init__(self, find: Callable | None = None, loader: Callable | None = None, threads: int = THREADS):
        self.find = find or _find_pair
        self.loader = loader or (lambda d: _CT2Pair(d, threads))
        self._loaded: dict = {}
        self._lock = threading.Lock()

    def missing(self, src: str, tgt: str) -> list[str]:
        return [ms.mt_pack_id(a, b) for a, b in route(src, tgt) if self.find(f"{a}_{b}") is None]

    def _get(self, pair: str):
        with self._lock:
            if pair not in self._loaded:
                self._loaded[pair] = self.loader(self.find(pair))
            return self._loaded[pair]

    def translate(self, text: str, src: str, tgt: str, cancel: Callable[[], bool] | None = None) -> str:
        cancel = cancel or (lambda: False)
        if not text.strip() or src == tgt:
            return text
        missing = self.missing(src, tgt)
        if missing:
            raise ModelMissing(missing)
        parts, layout = split_for_mt(text)
        for a, b in route(src, tgt):
            mt = self._get(f"{a}_{b}")
            out: list[str] = []
            for i in range(0, len(parts), BATCH):
                if cancel():
                    raise Cancelled()
                out.extend(mt.translate_batch(parts[i:i + BATCH]))
            parts = out
        return restore_layout(parts, layout)

    def unload(self) -> None:
        with self._lock:
            self._loaded.clear()


# --- summary -------------------------------------------------------------------------------------------
class _GenaiLLM:
    def __init__(self, model_dir, threads: int = LLM_THREADS):
        import onnxruntime_genai as og
        self.og = og
        cfg = og.Config(str(model_dir))
        cfg.overlay(json.dumps({"model": {"decoder": {"session_options": {
            "intra_op_num_threads": threads, "inter_op_num_threads": 1}}}}))
        self.model = og.Model(cfg)
        self.tok = og.Tokenizer(self.model)

    def generate(self, prompt: str, max_new_tokens: int, on_text=None, cancel=None, stop=None) -> str:
        og = self.og
        chat = json.dumps([{"role": "user", "content": prompt + " /no_think"}], ensure_ascii=False)
        ids = self.tok.encode(self.tok.apply_chat_template(chat, add_generation_prompt=True))
        params = og.GeneratorParams(self.model)
        params.set_search_options(max_length=len(ids) + max_new_tokens, do_sample=False)
        gen = og.Generator(self.model, params)
        gen.append_tokens(ids)
        stream = self.tok.create_stream()
        out = ""
        while not gen.is_done():
            if cancel and cancel():
                raise Cancelled()
            gen.generate_next_token()
            out += stream.decode(gen.get_next_tokens()[0])
            if on_text:
                on_text(out)
            if stop and stop(out):
                break
        return out


def _find_llm():
    return ms.installed_dir(ms.CATALOG[ms.LLM_PACK])


class LocalSummarizer:
    def __init__(self, find: Callable | None = None, loader: Callable | None = None, threads: int = LLM_THREADS):
        self.find = find or _find_llm
        self.loader = loader or (lambda d, t: _GenaiLLM(d, t))
        self.threads = threads
        self._llm = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return self.find() is not None

    def _get(self):
        with self._lock:
            if self._llm is None:
                d = self.find()
                if d is None:
                    raise ModelMissing([ms.LLM_PACK])
                self._llm = self.loader(d, self.threads)
            return self._llm

    @staticmethod
    def _one(llm, text: str, lang: str, on_text=None, cancel=None) -> str:
        show = (lambda t: on_text(clean_summary(t))) if on_text else None
        raw = llm.generate(summary_prompt(text, lang), SUMMARY_TOKENS, on_text=show, cancel=cancel,
                           stop=summary_should_stop)
        out = clean_summary(raw)
        if not out or strip_think(raw).startswith("<text>"):      # copied the input: ask once more
            out = clean_summary(llm.generate(summary_prompt(text, lang, instruction_last=True), SUMMARY_TOKENS,
                                             on_text=show, cancel=cancel, stop=summary_should_stop))
        return out

    def summarize(self, text: str, lang: str = "ko", on_text=None, cancel=None) -> str:
        chunks = chunk_text(dedupe_text(text), SUMMARY_CHUNK)
        if not chunks:
            return ""
        llm = self._get()
        if len(chunks) == 1:
            return self._one(llm, chunks[0], lang, on_text, cancel)
        parts = [self._one(llm, c, lang, cancel=cancel) for c in chunks]
        joined = "\n".join(parts)[:SUMMARY_CHUNK * 2]
        return self._one(llm, joined, lang, on_text, cancel)

    def unload(self) -> None:
        with self._lock:
            self._llm = None
