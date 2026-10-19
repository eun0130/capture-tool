# 회사용 정리 + 저장 폴더 검색 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v0.9.0 — the work edition sends nothing to the internet (no web search, no share link, Gemini replaced by a company LLM), and both editions search the saved captures by text, tags and look.

**Architecture:** Qt-free core modules (`company_llm`, `catalog`, `tagging`) with injected I/O (`post`, sqlite path, scandir), an `Indexer` service in the app layer that fills the catalogue off the GUI thread, a `SearchWindow` that only talks to `Catalog` and `controller.open_image_file`. Edition gating stays in `edition.py` + `WORK_EXCLUDES`.

**Tech Stack:** Python 3.12, PySide6, sqlite3 (FTS5 trigram), OpenCV/numpy, RapidOCR (already loaded), pytest offscreen. Spec: `docs/superpowers/specs/2026-10-20-work-edition-and-folder-search-design.md`.

Test command: `.venv\Scripts\python -X utf8 -m pytest tests/<file> -q`. Every task: failing test → code → green → commit.

---

## File map

| File | Responsibility |
|---|---|
| `capture_tool/core/company_llm.py` (new) | `CompanyLLM(key, endpoint, model, post, timeout)`: `generate`, `check`; `CompanyLLMError(kind)`; `MESSAGES`; `clean_endpoint()` |
| `capture_tool/core/settings.py` | `ai_endpoint`, `ai_model`, `catalog_text`, `catalog_enabled`, hotkey `search` |
| `capture_tool/edition.py` | `EXCLUDED_AT_WORK += ("search_web", "link_web", "gemini")`, `has_web_search()`, `has_share()` |
| `packaging/capture_tool.spec` | `WORK_EXCLUDES += websearch, lens, gemini` |
| `capture_tool/app/controller.py` | work gating in `on_toolbar_action`, `ai` property picks `CompanyLLM`, `_save` → `indexer.add(...)`, `CaptureMeta` from the picked window, `open_search()`, `find_similar()` |
| `capture_tool/app/side_bar.py` | search button: work = direct; home = menu with "내 캡처에서 찾기" first; link menu direct at work |
| `capture_tool/app/settings_dialog.py` | work: 회사 AI radio + endpoint/model/key; no share combo; both: 검색 group |
| `capture_tool/app/ai_ui.py` | consent text + `ENGINE` label per edition; `KeyDialog` work variant (endpoint/model/key) |
| `capture_tool/app/guide.py` | work substitutions for chapters 9 (검색) and 13 (링크), AI chapter; home chapter 9 gains 폴더 검색 step |
| `capture_tool/core/catalog.py` (new) | sqlite catalogue: `Catalog(path)`, `add`, `search`, `similar`, `reconcile`, `set_user_tags`, `set_text`, `pending`, `clear`, `Hit` |
| `capture_tool/core/tagging.py` (new) | `CaptureMeta`, `describe(img) -> Described`, `phash`, `hamming`, `colour_names`, `content_kind`, `keywords`, `auto_tags` |
| `capture_tool/platform/windows.py` | `process_name(hwnd) -> str` |
| `capture_tool/app/services.py` | `Indexer(catalog, ocr, folder_fn, busy_fn)`: `add(path, img, meta, lines)`, `rescan()`, `progress`, `pause` |
| `capture_tool/app/search_window.py` (new) | `SearchWindow(catalog, indexer, open_path, controller=None)` |
| `capture_tool/app/main.py` | tray "캡처 찾기…", hotkey `search` |
| `capture_tool/app/recent_strip.py` | thumbnails from the catalogue when present |
| tests | `test_company_llm.py`, `test_edition.py` (+ED_08..11), `test_ai_app.py` (+), `test_catalog.py`, `test_tagging.py`, `test_search_window.py`, `test_app.py` (+), `test_speed.py` (+SPD) |
| docs | bugs.md (none unless found), test-cases.md section, release-notes/v0.9.0.md, guide pictures unchanged, QUICK_START regenerate |

---

## Part A — 회사용

### Task A1: `CompanyLLM`
Test `tests/test_company_llm.py` (post injected; `post(url, body, headers, timeout) -> (status, bytes)`):
- CL_01 request shape: url `endpoint + "/v1/chat/completions"`, header `Authorization: Bearer KEY`, body model/messages/temperature 0.2; answer = `choices[0].message.content` stripped.
- CL_02 endpoint cleaning: trailing `/`, surrounding spaces removed; `/v1` already at the end is not doubled; non-http → `CompanyLLMError("config")`; empty → config.
- CL_03 errors: 401/403 → key, 429 → quota, 500/502/503 → server, 404 → model, 400 with "model" in body → model, 400 other → other, body without choices → other, `OSError` from post → network, finish_reason "content_filter" → blocked.
- CL_04 key never in `str(e)`, never in the url; `check()` calls generate with a short prompt and returns None / raises.
Code: mirror `core/gemini.py` structure.

### Task A2: settings + edition flags + spec excludes
- `Settings.ai_endpoint = ""`, `ai_model = ""`, `_apply`: strip; endpoint must start with http(s) else "" + warning.
- `edition.EXCLUDED_AT_WORK = ("kakao", "mail", "search_web", "link_web", "gemini")`; `has_web_search()`, `has_share()`, `has_gemini()`.
- spec `WORK_EXCLUDES += ["capture_tool.core.websearch", "capture_tool.platform.lens", "capture_tool.core.gemini"]`.
- Tests: `test_settings` (fields, validation), `test_edition.test_ED_08_the_work_edition_sends_nothing_out` (flags, spec text, `bar_layout.available_names()` still has "search" and "link").

### Task A3: controller gating + company LLM factory
- `on_toolbar_action`: `search_img:/search_text:` → if `not edition.has_web_search()`: `notify("회사용에서는 인터넷 검색을 쓰지 않습니다. 검색 버튼은 내 캡처 찾기입니다.")` and return. `link_web` → if `not edition.has_share()`: notify + return.
- `ai` property: work → `from ..core.company_llm import CompanyLLM`; `cloud_factory=lambda key: CompanyLLM(key, s.ai_endpoint, s.ai_model)`; `AiService` catches `CompanyLLMError` the same way as `GeminiError`: make `ai_service` catch a shared base — add `class CloudError(Exception)` in `core/ai_text.py`? Simpler: `GeminiError` and `CompanyLLMError` both subclass new `core/cloud_error.py:CloudError(kind)`; `ai_service` catches `CloudError`.
- Tests: `test_edition.test_ED_09_work_controller_ignores_web_search_and_share` (actions ignored, uploader never called, `_open_search` never called); `test_ai_app.test_AI_xx_work_edition_uses_company_llm` (factory type, empty endpoint → offline fallback note "회사 AI 서버 주소").

### Task A4: settings dialog + ai_ui + side bar + guide (work)
- `settings_dialog`: `has_share_section = edition.has_share()`; AI radio label at work "요약: 회사 AI (회사 LLM 서버 · 설정한 주소로 전송)"; `ai_endpoint`/`ai_model` QLineEdit at work; key button opens `KeyDialog` whose work variant has no AIza check, label "회사 AI 키"; `result_settings` writes them.
- `ai_ui.ENGINE` → function `engine_label(engine)`; consent dialog text per edition.
- `side_bar`: `search_menu()` at home gets first item "내 캡처에서 찾기" → action `search_local`; at work the button emits `search_local` directly. `_link_menu` at work emits `link_file` directly.
- `guide._AT_WORK` additions: chapter 9 title "9. 검색 (내 캡처 찾기)" with steps replaced; chapter 13 "인터넷 공유 링크" sentence removed; AI chapter "Gemini" → "회사 AI". Home chapter 9 gets a first step about 내 캡처 찾기.
- Tests: `test_ED_10_work_settings_and_guide_have_no_gemini_share_or_web_search` (dialog has no `share_expiry`, has `ai_endpoint`; guide text has no "구글"/"Gemini"/"인터넷 공유"/"렌즈"; home guide mentions 내 캡처 찾기), `test_ED_11_work_side_bar_search_and_link_go_straight_to_local` (search click emits `search_local`, link click emits `link_file`).

## Part B — 폴더 검색

### Task B1: `core/tagging.py`
Functions: `phash(img) -> int`, `hamming(a, b) -> int`, `colour_names(img) -> list[str]` (top 3), `content_kind(img, lines) -> str` (photo/table/code/text/ui), `size_class(w, h, screen=None) -> str`, `keywords(lines, n=5) -> list[str]`, `auto_tags(meta, described, lines) -> list[str]`, dataclasses `CaptureMeta(kind, app, title, taken)`, `Described(w, h, phash, colors, content, size_class)`; `describe(img, lines=None) -> Described`.
Tests `tests/test_tagging.py` TAG_01..06: phash identity/near/far (shifted 2px ≤ 10, random noise > 20), colours of painted rects, content: photo (noise gradient) / table (grid lines) / code (lines with indent + `{};=`) / text / ui (buttons), size class, keywords (frequency, drops 1-char and numbers, Korean 조사 stripped: 을/를/이/가/은/는/의/에/로/와/과/도), auto_tags composition.

### Task B2: `core/catalog.py`
`Catalog(db_path)`; `add(path, described, meta, text=None, tags=(), thumb=None) -> int`; `set_text(file_id, text, keywords)`; `search(query="", kind=None, content=None, app=None, since=None, colour=None, limit=200) -> list[Hit]`; `similar(phash, colors, limit=50)`; `reconcile(folder, entries: Iterable[(path, size, mtime)]) -> (added: list[Path], removed: int, moved: int)`; `pending(limit) -> list[(id, path)]`; `mark_failed(id)`; `set_user_tags(id, tags)`; `tags_of(id)`; `apps()`; `count()`; `thumb(id)`; `clear()`; `remove(id)`.
`Hit(id, path, name, taken, kind, app, content, colors, tags, snippet)`.
Text is stored through `redact.mask` always. Query: ≥3 chars per word → FTS `"word"` AND; shorter → LIKE on a concatenated column.
Tests `tests/test_catalog.py` CAT_01..10 per spec 3.7 (tmp_path db).

### Task B3: `platform/windows.process_name` + controller meta + indexer
- `windows.process_name(hwnd) -> str` (exe basename lower without .exe; "" on failure).
- controller: keep `self._picked_window` from `on_select_rect(window=)`; `_capture_meta(kind) -> CaptureMeta` (app via `process_name`, else `window_at` of the selection centre over `ov.windows`); `_save(img, kind=...)` call sites pass kind: finish("save"/"copy" autosave) → "area" or "window", scroll → "scroll", fullscreen, pin, table, open_image_file → "file".
- `services.Indexer(catalog, ocr_fn, read_ahead_fn, busy_fn, pool=None)`: `add(path, img, meta, lines=None)` queues (describe + thumb + text) on the pool; `rescan(folder)`; `progress -> (done, total)`; `on_change` callback (search window refresh). Sync mode (`pool=None`) runs inline for tests.
- Tests: `test_app.test_SAVE_xx_saving_adds_the_capture_to_the_catalogue` (fake indexer records path/meta.kind/app), `test_services.test_IDX_01_indexer_describes_and_reads_text_off_thread`, `IDX_02_rescan_backlog_pauses_while_busy`, `IDX_03_read_ahead_text_is_reused`.

### Task B4: `app/search_window.py`
`SearchWindow(catalog, indexer, open_path: Callable[[str], None], parent=None)`: `QLineEdit` query (debounced 150 ms, `sync` flag for tests), chips row (`QToolButton` checkable per kind/content/period + app `QComboBox` + colour combo), `QListWidget` icon mode with thumbs, status label, buttons 비슷한 그림 찾기… / 색인 지우기…; context menu; `run_search()`; `show_similar(path_or_img)`; drop handler; `results() -> list[Hit]` for tests.
Tests `tests/test_search_window.py` SW_01..06.

### Task B5: wiring — side bar `search_local`, tray, hotkey, settings group, recent strip thumbs
- controller `open_search()` (singleton window, `raise_`); `on_toolbar_action("search_local")` → `open_search()`; `search_similar` → `open_search(); window.show_similar(current capture)`.
- main.py tray action "캡처 찾기…"; hotkey `search` in DEFAULT_HOTKEYS and settings dialog hotkey rows.
- settings dialog group "검색": catalog_enabled, catalog_text checkboxes.
- recent strip: `RecentStrip.set_thumb_source(fn)`; controller passes `catalog.thumb_for(path)`.
- Tests: `test_app.test_SRCH_01_search_button_opens_the_search_window`, `test_recent_place` extension for thumb source, `test_settings_dialog` for the group, `test_hotkeys` default.

### Task B6: docs, speed, release
- `tests/test_speed.py`: SPD: `Catalog.search` over 10k synthetic rows < 50 ms; `_save` path with sync indexer stub adds < 10 ms on the GUI thread.
- `docs/test-cases.md` section "v0.9.0 추가", `docs/release-notes/v0.9.0.md`, `tools/make_quick_start.py` regenerate, `__version__ = "0.9.0"`, full suite, tag, publish both editions (after user approval for install).
