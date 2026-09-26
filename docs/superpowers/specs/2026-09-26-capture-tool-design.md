# 캡처 도구 설계 (v1)

작성일: 2026-09-26 · 상태: 승인됨 (mockup: https://claude.ai/artifact/XijyLXdvkWKsSokavWFypU)

## 1. 목표

Windows 10/11 사용자가 **Setup.exe 하나로 설치**해서 쓰는 무료 캡처 도구.
단축키 한 번으로 화면을 캡처하고, 그 자리에서 그리고, 어디든 붙여넣거나 저장한다.
이미지 속 텍스트와 도형을 인식해 텍스트로, 또는 **PowerPoint 네이티브 도형**으로 복사한다.

## 2. 확정된 결정

| 항목 | 결정 |
|---|---|
| 대상 | Windows 10(1809+)/11 x64, PowerPoint 365 |
| 개발 방식 | Claude Code loop/skill/agent로 개발, 완성 앱은 Claude 없이 동작 |
| 스택 | Python + PySide6 + RapidOCR(ONNX) + OpenCV + mss, PyInstaller + Inno Setup |
| OCR | 로컬 모델 내장 (한/영, 오프라인) |
| 도형 → PPT | **v1부터 네이티브** — `Art::GVML ClipFormat`(DrawingML) 직접 생성. SVG·PNG 동시 제공 |
| 기본 단축키 | **Win + ~** (캡처 + 그리기). 모든 단축키는 설정에서 언제든 변경 |
| 멀티 모니터 | 단축키를 누른 순간 **마우스가 있는 모니터**가 먼저 정지·준비됨 |
| 배포 | GitHub Releases, 무서명으로 시작, 관리자 권한 없이 사용자 폴더에 설치 |
| 라이선스 | MIT |
| 테스트 데이터 | 합성 이미지 자동 생성 (실사 샘플 불필요) |

## 3. 기능 범위 (v1)

1. **캡처 + 그리기** (Win + ~): 화면 정지 → 드래그로 영역 선택 → 툴바·팔레트가 바로 뜸
   - 도구: 선택, 사각형, 타원, 직선, 화살표, 곡선, 펜, 텍스트, 번호 스탬프, 형광펜, 모자이크
   - 스타일: 16색 팔레트 + 사용자 지정 + 최근 색, 두께 4단계, 채우기, 투명도
   - 편집: 실행 취소/다시 실행, 그린 도형 선택·이동·삭제
2. **마무리 동작**: Enter 복사, Ctrl+S 지정 폴더 저장, Ctrl+Shift+S 다른 이름으로, F3 화면에 고정, Esc 취소
3. **범용 붙여넣기**: 클립보드에 여러 형식 동시 제공 (이미지 PNG+DIB / 텍스트 UNICODE+HTML / 도형 GVML+SVG+PNG)
4. **텍스트 모드**: OCR, 부분 선택 복사, 표로 복사(TSV), 개인정보 자동 가림(이메일·전화·주민번호·카드번호), QR 인식
5. **도형 → PPT**: 사각형·둥근 사각형·원/타원·삼각형·직선·화살표 인식 + 색 + 도형 안 텍스트 → 네이티브 도형, 연결선은 도형에 연결
6. **선택 단계 보조**: 창·요소 자동 감지, 돋보기 + 색상 코드(HEX/RGB), 방향키 1px 이동
7. **화면에 고정**: 항상 위, 이동·확대·투명도, 더블클릭 닫기
8. **설정**: 단축키 녹화·충돌 경고, 저장 폴더·파일명 규칙·형식·자동 저장, 시작 시 실행
9. **v2로 미룸**: 스크롤 캡처, 캡처 기록, 배경 꾸미기, GIF 녹화

## 4. 아키텍처

```
capture_tool/
├─ core/                 # 화면 없는 순수 로직 — 전부 pytest 대상
│  ├─ geometry.py        # Rect, 모니터 탐색, 가상 화면, DPI 변환, 툴바 위치
│  ├─ hotkey.py          # 단축키 파싱·검증·충돌 검사
│  ├─ settings.py        # 설정 로드/저장 (손상 복구, 원자적 저장)
│  ├─ naming.py          # 파일명 규칙, 금지 문자, 중복 번호, 저장 폴더 대체
│  ├─ annotations.py     # 그리기 문서 모델, 실행 취소/다시 실행, 번호 스탬프
│  ├─ drawingml.py       # 도형 목록 → GVML(DrawingML) zip, SVG
│  ├─ clipboard_payload.py # 모드별 클립보드 형식 묶음, CF_HTML 헤더
│  ├─ redact.py          # 개인정보 탐지
│  ├─ table.py           # OCR 박스 → 행/열 → TSV
│  ├─ shapes.py          # 이미지 → 도형 인식 (OpenCV)
│  └─ ocr.py             # RapidOCR 래퍼 (지연 로딩, 예열)
├─ platform/             # Windows API 경계 (얇게 유지)
│  ├─ win_hotkey.py      # RegisterHotKey
│  ├─ win_clipboard.py   # 클립보드 쓰기 (재시도)
│  └─ screen.py          # mss/DXGI 캡처, 모니터 목록, 커서 위치
└─ app/                  # PySide6 화면
   ├─ tray.py, overlay.py, toolbar.py, palette.py, pin.py, settings_dialog.py
   └─ tools/             # 도구 1개 = 파일 1개
```

**원칙**: `core/`는 Qt·Windows API를 import하지 않는다. 그래서 agent가 사람 없이 검증할 수 있다.

## 5. 핵심 흐름

단축키 → `screen.cursor_monitor()` → 해당 모니터 먼저 캡처·오버레이 표시(나머지 모니터는 뒤이어) → 드래그 선택 → 툴바 → 그리기 → 마무리 동작별 처리:
- 복사: 합성 이미지 → `clipboard_payload.image()` → `win_clipboard.set()`
- 저장: `naming.render()` → `naming.unique_path()` → PNG/JPG 저장, 실패 시 대체 폴더
- 텍스트: `ocr` → `redact`(옵션) → `table`(옵션) → 텍스트 payload
- 도형: `shapes.detect()` + OCR 텍스트 매칭 → `drawingml.gvml()` + `svg()` + PNG

## 6. 속도 목표

| 구간 | 목표 |
|---|---|
| 단축키 → 커서 모니터 정지 화면 표시 | ≤ 150ms |
| Enter → 클립보드 | ≤ 50ms |
| OCR (1080p 영역) | ≤ 1s |

방법: 트레이 상주, 오버레이 창 미리 생성, OCR 모델 시작 시 백그라운드 예열, 인식은 요청 시에만.

## 7. 오류 처리 원칙

- 사용자 작업(캡처 이미지)은 어떤 오류에서도 잃지 않는다. 저장 실패 → 대체 폴더, 그것도 실패 → 클립보드에라도 남기고 알림.
- 클립보드 잠김 → 짧은 재시도(최대 5회, 20ms 간격) 후 알림.
- 단축키 등록 실패 → 트레이 알림 + 설정 창 열기.
- 설정 파일 손상 → `.bak`으로 보관 후 기본값.
- OCR 모델 로드 실패 → 텍스트/도형 기능만 비활성, 캡처는 정상.

## 8. 검증 (spike 결과, 2026-09-26)

- SVG 붙여넣기 + 도형으로 변환: 도형 4·텍스트 4 OK, 화살촉 손실, 텍스트 분리 → **채택 안 함**
- 직접 생성한 GVML 붙여넣기: 네이티브 둥근 사각형 4개(텍스트 내장), 연결선 3개(화살촉 유지, 도형에 연결) → **채택**

## 9. 테스트 전략

- 테스트 케이스 목록: `docs/test-cases.md` (로직·예외·경계 조건)
- TDD: 테스트 먼저 작성 → 실패 확인 → 구현 → 통과
- 도형 인식: 합성 이미지 생성기 + 정답 JSON, F1 ≥ 0.95 (합성)
- 수동 체크리스트: 단축키, 멀티 모니터·DPI 혼합, PPT 붙여넣기, Windows Sandbox 설치
