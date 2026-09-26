# 캡처 도구 (CaptureTool)

Windows용 무료 캡처 도구. 단축키 한 번으로 캡처하고, 그 자리에서 그리고, 어디든 붙여넣거나 저장합니다.
이미지 속 **한국어/영어 텍스트**를 오프라인으로 인식해 복사하고, 이미지 속 **도형을 PowerPoint에서 바로 편집 가능한 도형**으로 복사합니다.

> **처음 쓰시나요?** 다운로드부터 사용법, 문제 해결까지 그림과 함께 설명한 **[사용 가이드](docs/USER_GUIDE.md)** 를 보세요.

## 설치

1. [Releases](../../releases)에서 `CaptureTool-Setup-x.y.z.exe`를 받아 실행합니다.
2. 관리자 권한이 필요 없고, 따로 설치할 것(Python, 런타임, 언어팩)이 없습니다. 인터넷 없이도 동작합니다.
3. 코드 서명 전이라 "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.

## 사용법

| 동작 | 방법 |
|---|---|
| 캡처 + 그리기 | **Alt + ~** (숫자 1 왼쪽 키, Mac 키보드의 Option + ~) → 마우스가 있는 모니터가 즉시 멈춤 → 드래그로 영역 선택 |
| 빠른 실행 아이콘 | 선택한 이미지 옆에 뜨는 아이콘: **복사 · 저장(위치 선택) · 텍스트(OCR) · PPT로(PowerPoint를 열어 도형으로 붙여넣기) · 고정** |
| 창 통째로 선택 | 선택 단계에서 창 위에 마우스를 올리고 클릭 |
| 그리기 | 툴바: 사각형(R) 타원(O) 직선(L) 화살표(A) 곡선(C) 펜(P) 텍스트(T) 번호(N) 형광펜(H) 모자이크(M) · 색상 팔레트 · 두께 · 투명도 |
| 복사 | Enter — 메신저·메일·Word·PPT 등 어디든 Ctrl+V |
| 저장 | 저장 아이콘 또는 Ctrl+Shift+S → 위치·이름 선택 (마지막 폴더 기억) · Ctrl+S → 설정한 폴더에 바로 저장 |
| 화면에 고정 | F3 — 드래그 이동, 휠 확대, Ctrl+휠 투명도, 더블클릭 닫기 |
| 텍스트 복사 | 툴바 **텍스트** — OCR 결과 복사, 부분 선택, 표로 복사(Excel), 개인정보 자동 가림, QR 인식 |
| 도형 → PPT | 툴바 **도형→PPT** — PowerPoint에 Ctrl+V 하면 네이티브 도형(텍스트 포함, 화살표 연결 유지) |
| 색상 코드 | 선택 단계에서 C — 커서 위치 색상 HEX 복사 |
| 취소 / 되돌리기 | Esc / Ctrl+Z, Ctrl+Y · 방향키로 영역 1px 이동 |

모든 단축키는 트레이 아이콘 → **설정**에서 원하는 키를 눌러 바꿀 수 있습니다.

> 이전 버전의 기본값 Win + ~ 는 Windows Terminal "퀘이크 모드"와 겹쳐서 Alt + ~ 로 바뀌었고, 기존 설정도 자동으로 옮겨집니다.
> 단축키가 다른 프로그램과 겹치면 앱이 알려 주고 설정 창을 엽니다.

## 개발

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .[dev]
.\.venv\Scripts\python -m pytest -q          # 278 tests (unit, Windows API, UI, end-to-end)
.\.venv\Scripts\python run_capture.py         # 실행
.\.venv\Scripts\python run_capture.py --selftest   # 실제 화면에서 속도·OCR·도형 점검
.\build.ps1                                   # 테스트 → exe → installer\Output\Setup.exe (Inno Setup 6 필요)
```

구조: `capture_tool/core`(순수 로직, Qt·Windows 미사용) · `platform`(Windows API) · `app`(PySide6 화면).
설계: `docs/superpowers/specs/2026-09-26-capture-tool-design.md` · 테스트 케이스: `docs/test-cases.md`

## 라이선스

MIT. 포함된 구성요소의 라이선스는 `LICENSE` 하단 참고.
