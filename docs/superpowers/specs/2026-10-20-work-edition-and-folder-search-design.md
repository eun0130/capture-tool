# 회사용 외부 통신 정리 + 저장 폴더 검색 — 설계 (2026-10-20)

기준 버전 v0.8.35. 결과물은 v0.9.0(이 문서 전부, CLIP 팩 제외)과 v0.9.1(CLIP 팩).

## 1. 목표

1. **회사용 에디션**은 캡처 내용을 인터넷으로 내보내는 길이 없다: 웹 검색(그림·글자) 없음, 인터넷 공유
   링크 없음, Gemini 없음. 번역·요약의 클라우드 엔진은 **회사 LLM**(OpenAI 호환 엔드포인트, 설정에서
   주소·모델·키 입력)으로 바뀐다. 오프라인 번역·요약은 그대로. 파일 링크(저장 위치 경로)는 그대로.
2. **두 에디션 모두** 저장 폴더 안의 캡처를 **글자·태그·모양**으로 찾는다. 저장하는 순간 자동으로
   태그가 붙고, 찾은 그림은 지금처럼 모든 캡처 버튼으로 다시 연다. 전부 PC 안에서 돈다(통신 0).

## 2. 회사용 에디션

### 2.1 빠지는 것 (`edition.EXCLUDED_AT_WORK`, `packaging/capture_tool.spec WORK_EXCLUDES`)
- 버튼 코드 경로: `search_img:*`, `search_text:*`, `link_web` — 회사용에서 `on_toolbar_action`이 받으면 무시하고 알림.
- 모듈을 번들에서 제외: `core/websearch.py`, `platform/lens.py`, `core/gemini.py`. `core/share.py`는
  `file_link`가 남으므로 유지하되 `upload_litterbox`는 회사용에서 호출되지 않는다.
- 사이드바: 검색 버튼은 남고 **바로 폴더 검색 창**을 연다(메뉴 없음). 링크 버튼은 메뉴 없이 바로 파일 링크.
- 설정 창: 인터넷 공유 보관 시간 콤보, Gemini 라디오·키 마법사 없음. 대신 "요약: 회사 AI" 라디오와
  엔드포인트·모델·키 입력칸(키는 DPAPI, `ai_key` 재사용).
- 설명서(`guide.py`): 검색 장은 폴더 검색만, 링크 장은 파일 링크만, AI 장은 회사 AI 문구. `_WORK_SKIPS_TITLES`
  방식과 같은 치환표.
- 기존 설정의 `ai_key`(Gemini 키)는 회사용에서 그대로 회사 LLM 키 칸으로 쓰인다(둘 다 DPAPI 문자열).
  `share_expiry`·`share_consent`는 읽어도 쓰지 않는다.

### 2.2 회사 LLM (`core/company_llm.py`)
```python
class CompanyLLM:
    def __init__(self, key: str, endpoint: str, model: str, post=None, timeout=30): ...
    def generate(self, prompt: str) -> str      # POST {endpoint}/v1/chat/completions
    def check(self) -> None                     # 짧은 generate, 오류는 CompanyLLMError
class CompanyLLMError(Exception): kind in key/quota/network/server/blocked/model/config/other
```
- 본문 `{"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}`,
  헤더 `Authorization: Bearer <key>`, `Content-Type: application/json`. 응답 `choices[0].message.content`.
- HTTP 401/403 → key, 429 → quota, 5xx → server, 404/400(model) → model, 연결 실패 → network,
  엔드포인트 비어 있음 → config("설정 → AI에서 회사 AI 서버 주소를 넣어 주세요"). 메시지는 `MESSAGES` 표.
- `endpoint`는 `https://` 또는 `http://`로 시작해야 하고 끝의 `/`는 떼어 둔다. 키는 헤더에만, 로그에 없음.
- `AiService`는 바뀌지 않는다: `controller.ai`가 `edition.is_work()`이면
  `cloud_factory=lambda key: CompanyLLM(key, s.ai_endpoint, s.ai_model)`을 넘긴다. 엔드포인트가 비어 있으면
  `_cloud()`가 `CompanyLLMError("config")`를 내고 기존 폴백 규칙대로 오프라인으로 처리하며 그 메시지를 보여 준다.
- 동의 창(`ai_ui.py`): 회사용 문구 "글이 회사 AI 서버({endpoint})로 전송됩니다". `ENGINE` 이름표 "회사 AI".
- 설정: `ai_endpoint: str = ""`, `ai_model: str = ""` (`_apply` 검증: 문자열, 공백 제거, endpoint는 http(s)만).

### 2.3 테스트
- `tests/test_company_llm.py`: `post` 주입으로 본문·헤더·응답 파싱·오류 분기 전부; 키가 URL·예외 메시지에 없음.
- `tests/test_edition.py` 확장: 회사용에서 검색·링크 동작, 설정 창 위젯, 설명서 문구, spec의 WORK_EXCLUDES.
- `tests/test_ai_app.py`: 회사용 컨트롤러가 CompanyLLM 팩토리를 쓰고 엔드포인트 없으면 오프라인 폴백+알림.

## 3. 저장 폴더 검색

### 3.1 카탈로그 (`core/catalog.py`, Qt 없음)
- sqlite 파일 `%LOCALAPPDATA%\CaptureTool\catalog.db` (테스트는 경로 주입). 테이블
  - `files(id, path UNIQUE, folder, name, size, mtime, w, h, kind, app, title, taken, phash, colors, content, thumb BLOB, text_done)`
  - `tags(file_id, tag, source)` — source: auto / user
  - `fts(text, tags, name, app, title)` FTS5 `tokenize="trigram"`, `content=`없는 외부 콘텐츠 없이 자체 저장
- 키는 (path, size, mtime). 같은 폴더를 다시 훑을 때 셋이 같으면 건너뛴다.
- `Catalog.add(path, img, meta: CaptureMeta, text: list[Line] | None)`: 저장 직후 호출. 글자가 없으면
  `text_done=0`으로 두고 백그라운드 색인기가 나중에 읽는다.
- `Catalog.search(query, filters) -> list[Hit]`: 질의 3글자 이상이면 FTS `match`(각 낱말을 `"…"`로 감싸 AND),
  2글자 이하면 `LIKE`. 필터: kind, app, 기간, 색, content. 정렬: FTS rank, 같으면 최신순. 빈 질의 = 최신순 전체.
- `Catalog.similar(phash, colors, n) -> list[Hit]`: 해밍 거리 ≤ 10 우선, 그다음 색 히스토그램 거리. 사용자가 보기엔
  "비슷한 순".
- `Catalog.reconcile(folder, scandir)`: 없어진 파일 삭제, (size, phash)가 같은 새 경로는 이동으로 처리(행 유지), 새
  파일은 `text_done=0`으로 추가. 검색 창을 열 때와 색인기가 돌 때 호출.
- `Catalog.set_user_tags(file_id, tags)`, `Catalog.clear()`.
- 글자는 `redact.mask`를 거친 뒤 저장(설정 `redact_pii`와 무관하게 항상). 설정 `catalog_text=False`면 글자 색인 안 함.

### 3.2 자동 태그 (`core/tagging.py`, Qt 없음)
`CaptureMeta(kind, app, title, taken)`는 컨트롤러가 채운다:
- kind: area / window / fullscreen / scroll / table / pin / file(이미지 열기)
- app, title: `on_select_rect(window=)`로 받은 창(`WindowInfo`)에서. exe 이름은 `platform/windows.py`에
  `process_name(hwnd)` 추가(GetWindowThreadProcessId + QueryFullProcessImageNameW). 영역 선택이면 선택
  중심점 아래의 창(`window_at`).
그림에서 계산(`tagging.describe(img) -> Described`):
- content: photo(`ocr.looks_like_photo`) / table(격자: 가로·세로 긴 잉크 줄 3개 이상) / code(OCR 글의
  들여쓰기·기호 비율, `code_copy` 판정 재사용) / text / ui(그 외). OCR 결과 없으면 code·text 구분은 나중에.
- colors: 주색 3개(채도 있는 픽셀 기준 HSV 12구간 히스토그램)를 이름으로(빨강·주황·노랑·초록·청록·파랑·보라·분홍·검정·흰색·회색).
- phash: 64비트 DCT 해시(32×32 회색, 8×8 저주파, 중앙값).
- size class: full(모니터 크기 이상) / window(500px 이상) / piece.
- keywords: OCR 글에서 2글자 이상 낱말 빈도 상위 5개(숫자·조사 단독 제외). LLM 안 씀.
자동 태그 = kind, app, content, colors, size class, keywords, 창 제목 낱말(최대 5).

### 3.3 색인기 (`app/services.py`에 `Indexer`)
- QThreadPool 작업 하나가 큐를 비운다: 저장 직후 `add`(글자는 read-ahead 결과가 같은 픽셀이면 재사용, 아니면
  OCR), 백로그 파일(`text_done=0`)은 한 장씩. 오버레이가 떠 있는 동안·스크롤 캡처 중엔 멈춘다(`controller.busy`).
- 처음 켤 때 저장 폴더를 `reconcile`해 백로그를 만들고 트레이 툴팁에 "색인 중 n/m".
- 저장 폴더 설정이 바뀌면 새 폴더를 `reconcile`. 이전 폴더 행은 남긴다(검색 결과에 폴더 표시).
- 실패(읽을 수 없는 파일, OCR 예외)는 `text_done=-1`로 표시하고 다시 시도하지 않는다.

### 3.4 검색 창 (`app/search_window.py`)
- 열기: 사이드바 검색 버튼(회사용: 바로, 집용: 메뉴 첫 항목 "내 캡처에서 찾기"), 트레이 메뉴 "캡처 찾기…",
  단축키 `search`(기본 비어 있음, 설정에서).
- 위 검색칸(입력마다 150ms 뒤 검색), 아래 필터 칩: 종류(영역/창/스크롤/표/고정), 내용(글/표/사진/코드), 앱(색인된
  앱 목록), 기간(오늘/7일/30일/전체), 색. 오른쪽 "비슷한 그림 찾기…"(파일 고르기 또는 창에 그림 드롭).
- 결과: 썸네일 격자(카탈로그의 thumb, 132×84), 아래 파일명·날짜·앱. 더블클릭/Enter → `controller.open_image_file`.
  우클릭: 폴더에서 보기, 경로 복사, 태그 편집(쉼표로 구분, user 태그만 바뀜), 색인에서 빼기.
- 아래 상태줄: "n개 · 색인 중 a/b" · "색인 지우기…"(확인 창 뒤 `clear()` + 재색인).
- 편집 창(그리기 뒤) 사이드바 검색 메뉴에 "이 캡처와 비슷한 것 찾기" — 현재 캡처의 phash·색으로 `similar`.

### 3.5 설정
`catalog_text: bool = True`(글자 색인), `catalog_enabled: bool = True`, 단축키 `search`. 설정 창 "검색" 묶음.
`show_recent`의 recent strip은 카탈로그 썸네일이 있으면 그것을 쓴다(없으면 지금처럼 파일에서).

### 3.6 모양 검색 2단계 (v0.9.1, 별도 작업)
model_store 팩 "clip"(ViT-B/32 int8 ONNX, 이미지·텍스트 인코더). 설치돼 있으면 카탈로그에 `embed BLOB`
(512 float16)를 채우고, 검색칸의 질의를 오프라인 ko→en 번역기로 영어로 바꿔 텍스트 임베딩과 코사인 유사도로
"모양으로 찾기" 탭에 보여 준다. 없으면 탭이 숨겨진다. 이 문서는 자리만 잡아 둔다(`embed` 열은 v0.9.0에 미리 둠).

### 3.7 테스트
- `tests/test_catalog.py`: 추가·검색(3글자 FTS, 2글자 LIKE, 한국어 부분 일치, 대소문자), 필터, similar(해밍),
  reconcile(삭제·이동·새 파일), 사용자 태그, 마스킹된 글만 저장, clear.
- `tests/test_tagging.py`: 합성 그림으로 content·colors·size class·phash(같은 그림 0, 살짝 바뀐 그림 ≤ 10, 다른 그림 > 20)·keywords.
- `tests/test_search_window.py`(offscreen): 입력 → 결과, 필터 칩, 더블클릭이 `open_image_file`을 부름, 태그 편집, 드롭.
- `tests/test_app.py` 확장: 저장 직후 카탈로그 `add`가 메타(kind, app)와 함께 호출됨, read-ahead 재사용, 색인기가 오버레이 중엔 쉼.
- 속도: 저장 경로에 카탈로그 추가 비용 < 10ms(GUI 스레드에는 큐 넣기만), 1만 행 검색 < 50ms(`tests/test_speed.py`).

## 4. 범위 밖
- `_save_as`로 다른 폴더에 저장한 그림, 자동 저장을 끈 채 클립보드로만 간 캡처는 검색 대상이 아니다.
- 네트워크 폴더의 인덱스는 PC마다 따로다(공유 안 함).
- 회사 저장소 업로드(브리프 과제 A)는 하지 않는다 — 인터넷 공유 링크는 회사용에서 사라진다.
