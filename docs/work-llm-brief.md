# 회사용 캡처 도구 — 회사 AI·저장소 연동 작업 지시서

회사 안의 Claude Code(또는 다른 코딩 에이전트)에게 그대로 넘기는 문서입니다. 이 저장소를 받은 뒤 아래 과제를 순서대로 하면 됩니다.
작성 기준: v0.8.30 (2026-10-18). **v0.9.0(2026-10-20)에서 바뀐 것**:

- 과제 A(인터넷 공유 링크 → 회사 저장소)는 **하지 않기로 했습니다.** 회사용에는 인터넷 공유 링크 자체가 없고(`edition.EXCLUDED_AT_WORK`의 `link_web`), 링크 버튼은 파일 링크만 복사합니다. 회사 저장소 업로드가 꼭 필요하면 아래 2장을 참고해 `core/share_company.py`를 새로 만들고 `edition.has_share()` 분기를 다시 여세요.
- 과제 B(Gemini → 회사 LLM)는 **이미 구현돼 있습니다**: `core/company_llm.py`(OpenAI 호환 `POST {endpoint}/v1/chat/completions`, `Authorization: Bearer`), 설정 `ai_endpoint`·`ai_model`·`ai_key`(DPAPI), 설정 창·동의 창·키 창의 회사용 문구, `tests/test_company_llm.py`. 회사용 빌드에는 `core/gemini.py`가 들어가지 않습니다. 회사 API가 OpenAI 호환이 아니면 `company_llm.py`의 `generate`/`_parse`만 회사 규격에 맞게 고치면 됩니다(인터페이스는 `generate(prompt) -> str`, `check()`, `CompanyLLMError(kind)`).
- 과제 C의 "검색"은 회사용에서 **웹 검색 전부 제거**(구글 렌즈·구글·네이버·파파고, `search_web`)됐고, 대신 두 에디션 모두 저장 폴더 안을 찾는 **캡처 찾기**(`core/catalog.py`, `core/tagging.py`, `app/indexer.py`, `app/search_window.py`; sqlite+FTS5, 전부 PC 안)가 있습니다. 모델 미러(과제 C의 첫 항목)는 그대로 남은 과제입니다.
- 아래 2·3장은 v0.8.30 기준 설명으로 남겨 둡니다(구조 이해용).

## 0. 배경과 목표

- 캡처 도구는 Windows 화면 캡처 + 그리기 + OCR + 표·PPT 내보내기 앱입니다 (PySide6, Python 3.12, PyInstaller + Inno Setup).
- **회사용 에디션**(`build.ps1 -Edition work`)은 카카오톡·메일이 **빌드에서 빠진** 상태입니다 (`capture_tool/edition.py` `EXCLUDED_AT_WORK`, `packaging/capture_tool.spec` `WORK_EXCLUDES`).
- 회사용에 아직 남아 있는 외부 통신 네 가지가 이 문서의 대상입니다.

| 기능 | 지금 가는 곳 | 바꿀 것 |
|---|---|---|
| 전체 → 링크 → **인터넷 공유 링크** | litterbox.catbox.moe (익명 임시 호스트, 올린 뒤 삭제 불가) | **회사 파일 저장소/드라이브 API**로 올리고 회사 링크 반환 |
| 번역·요약의 **클라우드 엔진** | Google Gemini (사용자 개인 키) | **회사 LLM API** (OpenAI 호환 엔드포인트 권장) |
| 오프라인 AI 모델 내려받기 | huggingface.co, argos-net.com | 사내 미러 주소 설정 (선택) |
| 새 버전 확인·받기 | GitHub Releases (capture_work) | 설정 `update_source`에 사내 공유 폴더 경로 — **코드 수정 없음** |

지켜야 할 원칙(바꾸지 말 것): 오프라인이 기본, 외부 전송 전 **동의 창**, 텍스트 복사 전 **개인정보 가림**(`core/redact.py`), 인식한 글은 **로그에 남기지 않음**, 비밀값은 **DPAPI**(`platform/secret.py` `protect/unprotect`)로만 저장.

## 1. 저장소 지도

```
capture_tool/
  edition.py            에디션 판정(집/회사). 회사용에서 뺄 버튼 목록 EXCLUDED_AT_WORK
  core/                 순수 로직 (Qt 없음) — 여기에 새 연동 모듈을 둡니다
    share.py            인터넷 공유 링크: upload_litterbox(png, expiry, post) -> url
    gemini.py           Gemini 클라이언트: Gemini(key).generate(prompt) -> str, .check()
    ai_service.py       번역·요약 서비스. cloud_factory(key) 로 클라우드 엔진을 만듦
    settings.py         Settings 데이터클래스 + 검증(_apply). 새 필드는 여기에
    update.py           새 버전 확인·받기·검증·설치 (출처: GitHub / owner/repo / 폴더)
    model_store.py      오프라인 AI 모델 내려받기 (SHA-256 고정)
    redact.py           개인정보 가림
  app/                  Qt UI
    controller.py       모든 버튼의 동작. _share_web (링크), ai 프로퍼티 (AiService 생성)
    ai_ui.py            번역·요약 결과 창, Gemini 동의 창, Gemini 키 마법사
    settings_dialog.py  설정 창 (메일 항목처럼 에디션별로 숨김 가능: has_mail_section 참고)
    guide.py            앱 내 설명서 (회사용은 pages()에서 장·문구를 걸러냄)
  platform/secret.py    DPAPI protect/unprotect
tests/                  pytest (1,400여 개). 전체 14분 — 관련 파일만 돌리세요
packaging/capture_tool.spec, build.ps1, installer/CaptureTool.iss, tools/publish_work.ps1
```

개발 환경: `python -m venv .venv; .venv\Scripts\pip install -e .[dev]` 또는 기존 `.venv` 사용. 테스트는 `.venv\Scripts\python -X utf8 -m pytest tests/test_xxx.py -q`. Qt는 offscreen으로 돕니다.

## 2. 과제 A — 인터넷 공유 링크를 회사 저장소로

### 지금 구조
- `core/share.py` `upload_litterbox(png: bytes, expiry: str, post=None, timeout=60) -> str` — PNG를 올리고 https 링크를 반환. 실패는 `ShareError(메시지)`.
- `app/controller.py` `_share_web()`: `upload = self.uploader or upload_litterbox` → 워커 스레드에서 `upload(png_bytes, expiry)` → 링크를 클립보드에 (텍스트 + HTML). 동의 창 `_ask_share_consent_dialog()`에 Litterbox 설명이 박혀 있음.
- 설정: `share_expiry`(1h/12h/24h/72h), `share_consent`. 설정 창 `settings_dialog.py` 238행 근처 콤보.
- 버튼: `side_bar.py` `_link_menu` → `link_file`(로컬 경로 링크, 유지) / `link_web`.

### 할 일
1. `core/share_company.py` 새로 만들기: `upload(png: bytes, expiry: str, *, endpoint: str, token: str, post=None) -> str`.
   회사 API 규격(업로드 URL, 인증 헤더, 응답에서 링크를 꺼내는 법)에 맞춰 구현. `share.py`의 multipart 조립과 오류 처리(`ShareError`, 네트워크 오류는 "인터넷 연결" 메시지)를 그대로 본뜨세요. `expiry`는 회사 저장소가 지원하면 넘기고, 아니면 무시.
2. 설정 필드 추가 (`core/settings.py` `Settings` + `_apply` 검증): `share_endpoint: str = ""`, `share_token: str = ""`(DPAPI 암호화 저장, `ai_key`와 같은 방식 — `controller._ai_key` 참고).
3. 에디션 스위치: `controller._share_web`에서 `edition.is_work()`이면 회사 업로더를 쓰도록. 가장 단순한 방법은 `Controller.__init__`에서 `self.uploader = company_upload`(람다로 endpoint/token 주입). 엔드포인트가 비어 있으면 "설정 → 공유에서 회사 저장소 주소를 넣으세요" 알림 후 중단.
4. 동의 창 문구(`_ask_share_consent_dialog`)를 회사 저장소 기준으로 바꾸기 (누가 볼 수 있는지, 삭제 가능 여부). 설정 창에 엔드포인트·토큰 입력칸 추가(회사용에서만 보이게).
5. `core/share.py`의 `LINK_PREFIX` 검사는 Litterbox 전용 — 회사 모듈은 자체 검사(https 로 시작, 공백 없음).
6. 설명서 `guide.py` 13장 "링크" 문구, `docs/QUICK_START.md` 재생성(`tools/make_quick_start.py`).

### 테스트
- 새 테스트 `tests/test_share_company.py`: `post`를 주입해 요청 본문·헤더·응답 파싱·오류 분기를 검증 (`tests/test_app.py`의 `make` 픽스처로 컨트롤러 경로까지: `c.uploader`가 호출되고 링크가 클립보드에 가는지).
- 기존 통과 유지: `tests/test_edition.py`, `tests/test_settings.py`, `tests/test_guide.py`.

## 3. 과제 B — Gemini를 회사 LLM으로

### 지금 구조
- `core/ai_service.py` `AiService(settings, translator, summarizer, cloud_factory, get_key)`:
  `cloud_factory(key)`가 돌려주는 객체는 **`generate(prompt: str) -> str`** 하나만 있으면 됩니다. `_cloud()`에서 키가 없으면 오프라인으로, `ai_cloud_consent`가 False면 `ConsentNeeded` 예외 → UI가 동의 창을 띄움.
- `core/gemini.py` `Gemini(key, post=None, timeout=30)`: `generate(prompt)`, `check()`(키 검사), 오류는 `GeminiError(kind)` — kind: key/quota/network/server/blocked/model/other, 메시지는 `MESSAGES`.
- `app/controller.py` `ai` 프로퍼티(2340행 근처): `AiService(..., cloud_factory=Gemini, get_key=self._ai_key)`. `_ai_key`는 DPAPI로 푼 `settings.ai_key`.
- `app/ai_ui.py`: `ENGINE` 이름표, 동의 창(123행: "Google 서버로 전송"), 키 마법사(`KeyDialog`, 178행 `check`가 Gemini를 직접 만듦), `find_key`(AIza… 패턴).
- 설정: `ai_summary_engine`("local"/"cloud"), `ai_cloud_translate`, `ai_cloud_consent`, `ai_key`.

### 할 일
1. `core/company_llm.py`: `class CompanyLLM` — `__init__(self, key, endpoint, model, post=None, timeout=30)`, `generate(prompt) -> str`, `check()`.
   OpenAI 호환이면: `POST {endpoint}/v1/chat/completions`, 본문 `{"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}`, 헤더 `Authorization: Bearer <key>`, 응답 `choices[0].message.content`. 오류는 `GeminiError`와 같은 꼴의 자체 예외(`CompanyLLMError(kind)`)로 — UI가 `str(e)`를 그대로 보여 줍니다. 프록시는 `urllib.request.ProxyHandler`가 시스템 설정을 따르므로 보통 추가 작업 없음.
2. 설정 필드: `ai_endpoint: str = ""`, `ai_model: str = ""`. 키는 기존 `ai_key`(DPAPI) 재사용.
3. `controller.ai`에서 `edition.is_work()`이면 `cloud_factory=lambda key: CompanyLLM(key, settings.ai_endpoint, settings.ai_model)`.
4. `ai_ui.py`: 회사용일 때 `ENGINE["cloud"]`를 "회사 AI", 동의 창 문구를 "회사 AI 서버로 전송"으로, 키 마법사는 Gemini 안내(KEY_PAGE, find_key) 대신 "회사 토큰 붙여넣기 + 엔드포인트·모델" 입력으로. `check`는 `CompanyLLM(...).check()`.
5. `ai_service._cloud()`의 안내 문구 "Gemini 키가 설정되지 않아…"를 에디션에 맞게 (문자열만 바꾸면 됨).
6. 설명서(`guide.py` 번역·요약 장, 13장)와 설정 창 AI 항목 문구.

### 테스트
- `tests/test_company_llm.py`: `post` 주입으로 요청 본문·헤더·응답 파싱·오류 분기(401→key, 429→quota, 5xx→server, 네트워크→network).
- `tests/test_ai_app.py`, `tests/test_ai_engines.py`, `tests/test_ai_text.py`를 회사용(`CAPTURE_EDITION=work`)으로도 한 번 돌려 통과 확인. `tests/test_edition.py`에 "회사용은 Gemini를 쓰지 않는다" 케이스 추가 권장.

## 4. 과제 C(선택) — 모델 내려받기 미러, 검색

- `core/model_store.py` 52행 근처 `SOURCES`(HF, argos-net). 사내 미러를 쓰려면 기본 URL을 설정 필드(`model_mirror`)로 빼고 SHA-256 검증은 그대로 두세요.
- **검색**(구글·네이버 렌즈)은 브라우저만 열고 캡처는 클립보드에만 있습니다. 회사 정책상 막아야 하면 `edition.EXCLUDED_AT_WORK`에 `"search"`를 넣으면 버튼·동작·설명서가 모두 빠집니다 (메일과 같은 경로).

## 5. 빌드·배포

- 회사용 빌드: `.\build.ps1 -Edition work` → `installer/Output/CaptureTool-Work-Setup-x.y.z.exe` (+ 같은 이름 `.sha256`는 `release.yml`이 만듦; 수동 빌드면 `Get-FileHash`로 만들어 옆에 두세요).
- 사내 배포 폴더(예: `\\서버\소프트웨어\CaptureTool\`)에 설치 파일과 `.sha256`를 두고, 설정의 **업데이트 받을 곳**에 그 경로를 적으면 앱이 거기서 새 버전을 받습니다 (`core/update.py` 폴더 출처).
- 버전은 `capture_tool/__init__.py`와 `pyproject.toml` 두 곳. 릴리스 노트는 `docs/release-notes/vX.Y.Z.md`.

## 6. 완료 기준

- [ ] 회사용 빌드에서 `link_web`이 회사 저장소 링크를 돌려주고, litterbox 주소가 코드 경로에 남아 있지 않음 (`grep catbox`가 집용 분기에만).
- [ ] 회사용 빌드에서 번역·요약 "클라우드"가 회사 LLM으로 가고, `generativelanguage.googleapis.com`으로 나가는 요청이 없음.
- [ ] 동의 창·설정 창·설명서 문구가 회사 기준으로 바뀜. 개인정보 가림·오프라인 기본은 그대로.
- [ ] 새 테스트 + `tests/test_edition.py`, `tests/test_settings.py`, `tests/test_guide.py`, `tests/test_ai_*.py` 통과.
- [ ] `docs/test-cases.md`에 케이스 추가, `docs/bugs.md`는 버그일 때만.
