# 말로 모양 찾기 (CLIP 팩) — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v0.9.1 — 캡처 찾기 gains "모양으로": a Korean or English phrase ("막대 그래프", "확인 취소 버튼 대화 상자") finds the saved captures that look like it, entirely offline, through an optional model pack.

**Architecture:** One Qt-free module `core/shape.py` (tokenizer, preprocessing, ONNX sessions, `ShapeSearch`), the catalogue gains an `embed` API and `nearest()`, the indexer fills embeddings off the GUI thread, the search window gets a toggle and a pack-download flow through the controller. Spec: `docs/superpowers/specs/2026-10-20-work-edition-and-folder-search-design.md` §3.6.

**Tech Stack:** onnxruntime (already bundled), numpy, OpenCV, sqlite; model files from Hugging Face pinned by revision + SHA-256 in `core/model_store.py`.

Test command: `.venv\Scripts\python -X utf8 -m pytest tests/<file> -q`. Every task: failing test → code → green → commit.

---

## File map

| File | Responsibility |
|---|---|
| `capture_tool/core/model_store.py` | `CLIP_PACK = "clip-vit-b32-ml"`, 4 pinned files, kind "clip"; `clip_files(pack_dir) -> (vision, text, vocab, dense)` |
| `capture_tool/core/shape.py` (new) | `WordPiece`, `preprocess`, `load_safetensors`, `ClipModel`, `to_blob/from_blob`, `find_clip()`, `ShapeSearch` |
| `capture_tool/core/catalog.py` | `Hit.score`, `set_embed`, `pending_embed`, `embed_count`, `nearest`, `_filter_sql` |
| `capture_tool/app/indexer.py` | `embedder` param, `set_embedder`, embed on add + in the backlog |
| `capture_tool/app/search_window.py` | `shape` + `get_packs` params, 모양으로 toggle, nearest results, CLIP neighbours in look-alikes |
| `capture_tool/app/controller.py` | `shape` property, `_download_packs(..., on_progress)`, `open_search` passes shape/get_packs, `ai_idle` unloads |
| `capture_tool/app/main.py` | indexer gets the embedder when the pack is installed |
| `capture_tool/app/guide.py`, docs | 9장 step, USER_GUIDE, QUICK_START, test-cases, release notes v0.9.1 |

## Task 1: the pack (`model_store`)
- [ ] test `MS_12_clip_pack_is_pinned_and_its_files_are_found` (tests/test_model_store.py): pack in CATALOG, kind "clip", 4 files, sizes/hashes 64 hex, `clip_files(dir)` finds the four names, raises FileNotFoundError on an empty dir.
- [ ] code: `CLIP_PACK`, `_CLIP` table, `clip_files`.
- [ ] commit `feat: CLIP shape-search pack pinned in the model store`

## Task 2: `core/shape.py`
- [ ] tests (tests/test_shape.py): CLIP-01 WordPiece on a tiny vocab (`[CLS]`/`[SEP]`, `##` pieces, `[UNK]`, 한자 split, punctuation split, 128 cap); CLIP-02 `preprocess` → (1,3,224,224) float32, centre crop of a wide image, value of a white pixel = (1-mean)/std; CLIP-03 `load_safetensors` on a file written by the test; CLIP-04 `ClipModel` with fake sessions returns unit vectors and feeds mask/ids; CLIP-05 blob round trip float16; CLIP-06 `ShapeSearch`: `available()` false without pack, `missing()`, lazy one-time load under lock, `unload()`.
- [ ] code.
- [ ] commit `feat: core/shape.py - multilingual CLIP text/image embeddings, Qt-free`

## Task 3: catalogue embeddings
- [ ] tests CAT-11 (set_embed, pending_embed, embed_count, b"" means failed-not-pending), CAT-12 (nearest order by cosine, min_score, filters, Hit.score, rows without embed skipped), SPD-14 (10k rows nearest < 60 ms).
- [ ] code.
- [ ] commit `feat: catalogue stores CLIP embeddings and answers nearest()`

## Task 4: indexer
- [ ] test IDX-05: with a fake embedder, `add` stores a blob; backlog fills rows that lack one; `set_embedder` later + `run_backlog` fills old rows; an embedder exception marks b"".
- [ ] code.
- [ ] commit `feat: indexer embeds captures for shape search`

## Task 5: search window
- [ ] tests SW-07 (toggle on → nearest results, status, chips still narrow, toggling off returns to words), SW-08 (pack missing: ask → no → toggle off; ask → yes → get_packs called → done(True) → results), SW-09 (look-alikes append CLIP neighbours).
- [ ] code.
- [ ] commit `feat: 캡처 찾기 - 모양으로 toggle with pack download`

## Task 6: controller + main
- [ ] tests CAPP-11: `open_search` hands shape/get_packs; `_download_packs` without an AI window reports through `on_progress` and `done`; `ai_idle` unloads shape.
- [ ] code; main.py wires `indexer.set_embedder` when `shape.available()`.
- [ ] commit `feat: shape search wired - pack download from the search window, idle unload`

## Task 7: real-model measurement, docs, release
- [ ] `tests/test_shape_real.py` (skips without the pack): 4 Korean queries rank the matching synthetic picture first; timings recorded in test-cases.md.
- [ ] guide 9장 (home + work) one step; USER_GUIDE; `python tools/make_quick_start.py`; docs/test-cases.md v0.9.1; docs/release-notes/v0.9.1.md; work-llm-brief mirror row mentions the clip pack; `__version__ = "0.9.1"`.
- [ ] full suite, selftest both editions, commit, tag v0.9.1, publish home + work.
