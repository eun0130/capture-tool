# macOS 지원 (범위 1: 핵심 캡처) 설계

날짜: 2026-10-24 · 대상 버전: v0.10.0 · 기기: Apple Silicon (M4), macOS 14 이상

## 1. 목표와 범위

집용 에디션을 맥에서도 쓴다. 범위는 **핵심 캡처**: 영역·창·전체·스크롤 캡처, 편집, 복사·저장·PDF·인쇄,
글자·표 인식 복사, 메일(mailto)·웹 검색, 캡처 찾기·모양으로, 번역·요약.

맥에 없는 것(이번 범위 밖): PowerPoint 네이티브 도형·Excel·Word 보내기(Office COM), 카카오톡 창 제어,
Google Lens 붙여넣기, DRM·보안 SW 감지. 그림은 클립보드로 가므로 Keynote/PowerPoint에는 Cmd+V로 붙인다.
회사용 에디션은 맥에 만들지 않는다(회사 PC는 Windows).

성공 기준: 맥에서 `python -m capture_tool --selftest` OK, 수동 체크리스트(§9) 통과, `CaptureTool-<v>-mac.dmg`가
capture_dist 릴리스에 올라가고 업데이터가 그것을 본다. Windows 쪽은 동작·테스트 모두 불변.

## 2. 구조: OS별 platform 층, 나머지 공유

지금 `capture_tool/platform/`은 전부 Windows 구현(1,760줄)이고, app 층이 모듈 이름으로 직접 가져온다
(`services.py`·`hotkeys.py`·`main.py`·`toast.py`·`controller.py`·`overlay.py`). core(22,600줄 중 나머지)는 Qt·numpy·onnx뿐이라
그대로 돈다.

바꾸는 것:

- `capture_tool/platform/__init__.py`가 **백엔드 선택기**가 된다. `sys.platform == "darwin"`이면 `platform.mac.*`, 아니면
  지금의 Windows 모듈. app 층은 `from ..platform import backend` 뒤 `backend.screen`, `backend.clipboard`, `backend.hotkey`,
  `backend.windows`, `backend.scroll`, `backend.startup`, `backend.secret`, `backend.shell`처럼 쓴다. 테스트는
  `platform.use(fake)`로 바꿔 끼운다(지금 `RealScreen`/`RealClipboard` 주입 방식은 유지, 안쪽만 백엔드 경유).
- Windows 모듈은 **자리·이름 그대로** 둔다(`screen.py`, `win_clipboard.py`, `win_hotkey.py`, `windows.py`, `scroll.py`,
  `startup.py`, `secret.py`, …). 테스트 1,537개·bugs.md의 회귀 테스트 경로가 그대로다. 선택기가 이름만 맞춰 준다
  (`backend.clipboard`는 Windows에서 `win_clipboard`).
- 새 모듈 `platform/shell.py`(공통): `open_path(path)`(폴더·파일 열기), `reveal(path)`(탐색기/Finder에서 보이기),
  `open_url(url)`. Windows는 `os.startfile`·`explorer /select,`, 맥은 `open`·`open -R`. 지금 `controller._open_folder`·
  `_reveal_file`·`_open_url`, `main.py`의 `os.startfile`, `update.launch_installer`의 `cmd.exe` 호출이 이리로 모인다.
- Windows 전용 모듈(`excel`, `word`, `powerpoint`, `kakao`, `lens`, `security_software`)은 맥 백엔드에 없고, app 층은
  §3의 기능 가림 때문에 맥에서 그것들을 부르지 않는다. 가져오기는 지금처럼 함수 안에서 늦게 한다.

맥 백엔드 `capture_tool/platform/mac/`:

| 모듈 | 함수 (Windows 쪽과 같은 서명) | 구현 |
|---|---|---|
| `screen.py` | `monitors()`, `cursor_pos()`, `grab(rect)`, `set_dpi_awareness()`(no-op) | 모니터·배율은 Qt `QScreen`(물리 px = 논리 × devicePixelRatio), 그림은 `mss`(이미 의존성, 맥 지원), 커서는 `NSEvent.mouseLocation`을 물리 px·위쪽 원점으로 뒤집음 |
| `clipboard.py` | `set_formats(payload)`, `get_format(name)`, `get_text()`, `ClipboardBusy` | `NSPasteboard`: `PNG`→`public.png`, `HTML Format`→`public.html`(헤더 제거), `CF_UNICODETEXT`→`public.utf8-plain-text`, `image/svg+xml`→`public.svg-image`; `CF_DIB`·GVML은 Windows 전용이라 건너뜀 |
| `hotkey.py` | `register(hwnd, id, hk)`, `unregister(hwnd, id)` | Carbon `RegisterEventHotKey`(ctypes, 권한 불필요). 조합 플래그·가상 키 코드표는 순수 함수 `carbon_keys(hk)` |
| `windows.py` | `top_level_windows()`, `window_at()`, `process_name()`, `capture_window()`, `bring_to_front()`, `WindowInfo` | `CGWindowListCopyWindowInfo`(layer 0, on-screen), `CGWindowListCreateImage`, `NSRunningApplication.activateWithOptions_` |
| `scroll.py` | `wheel()`, `set_cursor()`, `esc_pressed()`, `display_affinity()`(항상 0), `exclude_from_capture()`, `is_browser()`, `browser_viewport()`(None = 창 전체), `root_window_at()` | `CGEventCreateScrollWheelEvent`+`CGEventPost`, `CGWarpMouseCursorPosition`, `CGEventSourceKeyState`, 창의 `NSWindow.sharingType = NSWindowSharingNone`, 번들 ID로 브라우저 판별 |
| `startup.py` | `set_enabled(enabled, exe_path)`, `is_enabled()` | `~/Library/LaunchAgents/com.capturetool.plist`(RunAtLoad, `--tray`); plist 본문은 순수 함수 `plist_text(exe)` |
| `secret.py` | `protect(text)`, `unprotect(blob)`, `SecretError` | 키체인: `security add-generic-password -U` / `find-generic-password -w`, 서비스 이름 `CaptureTool`; 저장값은 키체인 항목 이름 |
| `shell.py` | §2 공통 모듈의 맥 쪽 | `open`, `open -R` |
| `permissions.py` | `screen_recording()`, `request_screen_recording()`, `accessibility()`, `open_settings(pane)` | `CGPreflightScreenCaptureAccess`/`CGRequestScreenCaptureAccess`, `AXIsProcessTrustedWithOptions`, `open x-apple.systempreferences:…Privacy_ScreenCapture` |

좌표 규칙은 Windows와 같다: app 층은 **물리 px, 왼쪽 위 원점**만 본다. y축 뒤집기·배율 곱하기는 mac 모듈 안에서만 한다.

`hotkeys.py`의 `HotkeyWindow`는 Windows에서 `WM_HOTKEY`를 받는 숨은 창이다. 맥에서는 Carbon 이벤트 핸들러가 콜백으로
`manager.dispatch(id)`를 부르므로 `HotkeyWindow`는 백엔드가 주는 `register/unregister`만 쓰고 `nativeEvent`는 Windows에서만
의미 있다(맥에서는 호출되지 않음, 코드는 그대로).

## 3. 기능 가림: edition과 같은 메커니즘

`capture_tool/edition.py`에 OS 제외 목록을 더한다.

```python
EXCLUDED_ON_MAC = ("ppt", "ppt_shapes", "ppt_merge", "excel", "word", "kakao", "lens", "drm")
def excluded() -> tuple[str, ...]:   # edition 제외 + OS 제외의 합집합
```

`has(name)`을 보는 곳(`bar_layout`, `side_bar`, 안내 페이지, 설정)이 그대로 맥에서 단추·안내·설정 항목을 뺀다.
회사용에서 카카오를 빼는 것과 같은 길이라 새 분기가 app 층에 생기지 않는다. `controller`의 `detect_drm()`은
`has("drm")`이 거짓이면 부르지 않는다(`self.drm = None`).

남는 단추는 Windows 집용과 같다: 저장·다른 이름·폴더 열기·링크·인쇄·PDF·테두리·투명·크기·글자·표·검색·메일·고정 등.
`print_image`는 Qt `QPrintDialog`라 그대로.

## 4. 단축키

- 파서(`core/hotkey.py`)는 이미 `cmd`·`command`를 `win` 수식키로 받는다. 표시 이름만 OS별: 맥에서는 `Win`→`Cmd`,
  `Alt`→`Option`(`_MOD_LABEL`을 함수로).
- 맥 기본값: 캡처 `Option + ~`(2026-10-29 변경 — Windows `Alt + ~`와 같은 키라 두 PC에서 손에 익은 대로; 맥에서 실측 동작,
  예약·충돌 없음). 처음 설계는 `Cmd+Shift+2`(시스템 `Cmd+Shift+3/4/5` 옆)였음. Windows 기본값 `Alt + ~`는 그대로.
  `settings.py`의 `DEFAULT_HOTKEYS`는 OS별 사전이 된다. 설정 파일에 값이 있으면 그것을 쓴다(지금과 같음).
- 충돌표(`known_conflicts`)에 맥 항목: `Cmd+Shift+3/4/5`(시스템 캡처), `Cmd+Space`(Spotlight), `Cmd+Tab`, `` Cmd+` ``(창 전환),
  `Cmd+Q/W/H/M`.
- Carbon 키 코드표: 글자·숫자·F키·기호 ≈ 60개를 `mac/hotkey.py`에 상수 사전으로 둔다. 표에 없는 키는 등록 실패
  메시지("이 키는 맥에서 쓸 수 없습니다").

## 5. 권한과 첫 실행

맥은 화면 기록(캡처·창 목록 이름)과 손쉬운 사용(스크롤 휠 이벤트·커서 이동)을 사용자가 시스템 설정에서 직접 켜야 한다.

- 시작 때 `permissions.screen_recording()`이 거짓이면 `request_screen_recording()`(시스템 대화상자 한 번) 뒤,
  여전히 없으면 **안내 창**: "시스템 설정 > 개인정보 보호 및 보안 > 화면 기록에서 캡처 도구를 켜고 다시 실행". 단추로
  설정 창 열기. 캡처 단축키를 눌렀는데 권한이 없으면 같은 안내를 토스트로.
- 스크롤 캡처를 처음 누를 때 손쉬운 사용이 없으면 같은 식의 안내(스크롤만 막힘, 다른 캡처는 됨).
- 안내 페이지(`guide.py`)에 맥 전용 페이지 1장 "맥에서 처음 쓰기"(권한 2개, 우클릭 > 열기, 단축키 Option+~).
  Windows 빌드에는 안 보인다(`has("mac_guide")`식이 아니라 `sys.platform` 판단은 guide.py 한 곳).
- 메뉴 막대 앱: `Info.plist`의 `LSUIElement=1`(Dock 아이콘 없음). 지금 트레이 메뉴가 메뉴 막대 아이콘이 된다(Qt
  `QSystemTrayIcon`이 맥에서 메뉴 막대로 감).

## 6. 빌드·배포

- 의존성(`pyproject.toml`): `pywin32; sys_platform == "win32"`, `pyobjc-framework-Cocoa; sys_platform == "darwin"`,
  `pyobjc-framework-Quartz; sys_platform == "darwin"`. `onnxruntime`·`rapidocr`·`ctranslate2`·`onnxruntime-genai`·`mss`는
  arm64 macOS 휠이 있다(설치 때 확인, 없으면 그 기능만 가림).
- `packaging/capture_tool.spec`: `sys.platform == "darwin"`이면 `BUNDLE(coll, name="CaptureTool.app", icon="assets/app.icns",
  bundle_identifier="com.capturetool.app", info_plist={LSUIElement, NSScreenCaptureUsageDescription,
  NSAppleEventsUsageDescription, CFBundleShortVersionString})`. 맥 빌드에서 Windows 전용 모듈은 `excludes`에.
  `assets/app.icns`는 `tools/make_icon.py`가 기존 아이콘에서 만든다.
- `build.sh`(맥): 테스트 → PyInstaller → ad-hoc 서명(`codesign --force --deep -s -`) → `hdiutil create`로
  `installer/Output/CaptureTool-<v>-mac.dmg`(앱 + Applications 링크) → `.sha256`.
- `release.yml`: `macos-latest`(arm64) 잡 추가. 테스트는 `-m "not windows and not mac and not slow and not timing"`.
  태그 빌드면 dmg를 본 리포 릴리스와 capture_dist 릴리스에 함께 올린다(집용만). `publish_work.ps1`에는 손대지 않는다
  (회사용은 Windows만).
- 서명·공증 없음(Apple 개발자 계정 없음): 처음 열 때 "확인되지 않은 개발자" → 우클릭 > 열기. 안내 페이지·릴리스 노트에
  적는다. 나중에 계정이 생기면 `codesign`·`notarytool` 단계만 추가.
- 업데이터(`core/update.py`): `INSTALLER`/`_PATTERN`에 `mac` 항목(`CaptureTool-{v}-mac.dmg`). 맥에서는 `check`→`download`→
  `verify`까지 같고, `launch_installer`는 dmg를 `open`한 뒤 "CaptureTool을 응용 프로그램 폴더로 끌어 넣고 다시
  실행하세요"를 알린다(자동 교체는 이번 범위 밖). 플랫폼 키는 `edition`과 별개 인자 `platform`으로 받는다.
- 사용자 데이터 위치: 설정 `~/Library/Application Support/CaptureTool/`, 모델 팩 같은 폴더 아래 `models/`
  (`model_store.user_root`·`settings_path`가 OS별). 저장 폴더 기본값 `~/Pictures/캡처`.

## 7. 테스트

- 순수 논리는 Windows에서도 도는 단위 테스트(`tests/test_mac.py`, Qt·pyobjc 없이): 좌표 뒤집기(`flip_rect`), Carbon
  키 코드·수식키 변환, 클립보드 포맷 매핑(PNG/HTML/텍스트, DIB·GVML 건너뜀), plist 본문, 업데이터 mac 자산 선택,
  `edition.excluded()`의 OS 합집합(`CAPTURE_PLATFORM=darwin` 환경 변수로 비프로즌 빌드에서만 흉내), 설정 기본 단축키·경로.
- `mac` 마커: 실제 Quartz·NSPasteboard·Carbon을 쓰는 테스트(`tests/test_mac_real.py`), 맥에서만. `windows` 마커와 대칭.
- 백엔드 선택기 테스트: darwin이면 mac 모듈, win32면 기존 모듈, `use(fake)`로 교체·복원.
- `--selftest`가 맥에서 그대로 돈다(클립보드 읽기는 백엔드의 `get_format("PNG")`).
- CI: Windows 잡 그대로 + macOS 잡(offscreen, `not windows and not mac`).

## 8. 진행 순서

1. **이 PC(Windows)**: §2 선택기·`shell.py`·§3 가림·§4 파서 표시·§6 의존성 마커·업데이터 mac 항목·§7 순수 논리 테스트.
   Windows 동작 불변 — 전체 테스트·selftest 통과, 커밋(릴리스 없음).
2. **맥(Claude Code를 맥에 깔고 같은 리포)**: `platform/mac/*` 구현, 권한 안내, 안내 페이지, `mac` 마커 테스트,
   selftest, 수동 체크리스트. 이 세션(Windows)은 맥 코드를 실행할 수 없으므로 실행·수정은 맥 세션이 한다.
3. dmg 빌드 스크립트·spec `BUNDLE`·release.yml 맥 잡·배포 v0.10.0. 설치는 맥에서 사용자가 직접(우클릭 > 열기).

## 9. 맥 수동 체크리스트

- [ ] 처음 실행: 화면 기록 권한 요청 → 설정에서 켜기 → 재실행 후 메뉴 막대 아이콘
- [ ] `Option+~` → 커서 있는 모니터 정지 화면(내장 Retina + 외장 모니터, 배율 다를 때)
- [ ] 영역·창(커서 아래 창 테두리)·전체·스크롤(손쉬운 사용 권한) 캡처
- [ ] 복사 → 미리보기·Keynote·PowerPoint·메모·Slack에 Cmd+V
- [ ] 저장 폴더·PDF·인쇄·글자 복사·표 복사·캡처 찾기·모양으로(팩 받기)
- [ ] 시작 시 실행 켜고 재로그인
- [ ] 업데이트 확인 → dmg 열림 → 교체 후 버전 표시
- [ ] 토스트·오버레이가 캡처 결과에 안 찍힘

## 10. 범위 밖(나중)

Office 도형(AppleScript), 자동 업데이트 교체, 서명·공증, Intel 빌드(universal2), 회사용 맥, 카카오·Lens.
