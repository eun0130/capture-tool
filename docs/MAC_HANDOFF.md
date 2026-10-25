# 맥에서 이어서 하기 — Paseo + Claude Code (v0.10.0 맥 지원)

Windows 쪽 준비는 전부 끝나 `main`에 있습니다. 맥에서 남은 일은 **미리 써 둔 맥 코드를 실제로 돌려 보고 터지는 곳을
고치는 것**이며, 그 일은 Paseo 안의 Claude 에이전트가 합니다. 사람이 손으로 하는 것은 1장의 설치 몇 단계와, 진행 중
권한 창을 켜 주고 "되는지 안 되는지" 답해 주는 것뿐입니다.

## 0. 맥 기본 조작 (처음이라면)

- **터미널 열기**: `Cmd + Space` → `터미널` 입력 → `return`. 검은(흰) 글자 창이 터미널입니다.
- **붙여넣기**: `Cmd + V`. 아래 명령은 **한 줄씩** 붙이고 `return`. 다음 줄은 앞 줄이 끝나고(프롬프트 `%`가 다시 보이면) 붙입니다.
- **암호**: 터미널이 `Password:` 를 물으면 맥 로그인 암호를 치고 `return`. 글자가 안 보여도 입력되고 있는 것입니다.
- **앱 설치(dmg)**: 받은 `.dmg`를 두 번 눌러 열고, 앱 아이콘을 **응용 프로그램(Applications)** 폴더로 끌어 넣습니다.
- **처음 여는 앱 경고**("확인되지 않은 개발자", "열 수 없음"): 응용 프로그램 폴더에서 앱을 **우클릭(두 손가락 클릭) > 열기**.
- **권한**: 시스템 설정 > 개인정보 보호 및 보안 > **화면 기록** / **손쉬운 사용**. 스위치를 켠 뒤 그 앱을 완전히 종료하고 다시 엽니다.

## 1. 사람이 하는 설치 (한 번, 20~40분, 대부분 기다리기)

### 1-1 Homebrew (맥용 패키지 설치기)
터미널에 붙이고 `return` → "Press RETURN" 에 `return` → 암호.
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
끝나면 화면에 `Next steps:` 아래 `eval "$(/opt/homebrew/bin/brew shellenv)"` 로 시작하는 두 줄이 보입니다. 그 두 줄도 그대로 붙여 실행합니다.

### 1-2 GitHub 로그인 (리포가 비공개)
```
brew install gh
```
```
gh auth login
```
질문이 차례로 나옵니다. 방향키로 고르고 `return`: **GitHub.com** → **HTTPS** → `Y` → **Login with a web browser** →
화면의 8자리 코드를 적어 두고 `return` → 브라우저가 열리면 GitHub 로그인 후 코드 입력 → **Authorize**.

### 1-3 리포 받기 + 환경 준비 (한 줄, 10~20분)
```
gh repo clone eun0130/capture-tool ~/capture-tool && ~/capture-tool/tools/mac_bootstrap.sh
```
파이썬 3.12, 가상환경, 의존성, OCR·번역 모델, Claude Code 를 설치하고 테스트를 한 번 돌립니다.
테스트가 몇 개 실패해도 괜찮습니다(그걸 고치는 게 에이전트의 일). 마지막에 `== 준비 끝` 이 보이면 됩니다.

### 1-4 Claude Code 로그인
```
claude
```
처음 실행이면 로그인 안내가 나옵니다(브라우저에서 Anthropic 계정 로그인). 끝나면 `/exit` 로 나옵니다.
`claude: command not found` 가 나오면 터미널을 닫고 새로 열어 다시 시도합니다.

### 1-5 Paseo 설치
```
brew install --cask paseo
```
(또는 https://paseo.sh/download 에서 **Apple Silicon** dmg를 받아 응용 프로그램으로 끌어 넣기. macOS 13 이상.)
`Cmd + Space` → `Paseo` → `return` 으로 실행합니다. 처음 열 때 경고가 나오면 우클릭 > 열기.

### 1-6 Paseo 에서 프로젝트 열기
1. 왼쪽 사이드바에서 프로젝트 추가(폴더 열기) → `~/capture-tool` 선택. 안 보이면 터미널에서:
   ```
   /Applications/Paseo.app/Contents/Resources/bin/paseo project create ~/capture-tool
   ```
2. **New workspace** → `capture-tool` 프로젝트 선택 → **Isolation** 은 **Local**(그 폴더 그대로, `main` 브랜치에서 작업).
3. 작업 공간이 열리면 **New agent** → 제공자 **Claude Code** → 권한 모드는 **bypass**(묻지 않고 진행; 삭제 명령은 리포의
   훅이 따로 묻습니다) → 아래 2장의 프롬프트를 통째로 붙이고 보냅니다.

Paseo 가 "claude 를 찾을 수 없다"고 하면: Paseo 를 완전히 종료(`Cmd + Q`)하고 다시 열거나, Paseo 의 Settings > Providers >
Claude Code > Diagnostic 에서 경로를 확인합니다(Claude Code 는 `~/.local/bin/claude`).

## 2. 에이전트에게 붙일 프롬프트

```
맥에서 캡처 도구 v0.10.0 맥 지원(1단계)을 이어서 진행해. 먼저 CLAUDE.md, docs/MAC_HANDOFF.md,
docs/superpowers/specs/2026-10-24-macos-port-design.md, docs/superpowers/plans/2026-10-24-macos-port.md 를 읽어.

상태: 계획의 Task 1~8(Windows 쪽)은 끝나서 main 에 있어. Task 9~16 의 코드(capture_tool/platform/mac/*,
app/main.py 의 권한 확인, app/guide.py 의 맥 페이지, packaging/capture_tool.spec 의 BUNDLE, build.sh,
.github/workflows/release.yml 의 mac 잡, tests/test_mac_real.py)도 Windows 에서 미리 써 두었지만 맥에서는 한 번도
실행하지 않았어. 네 일은 그것을 이 맥에서 실제로 돌려 보고 터지는 곳을 고치는 것.

순서:
1. tools/mac_bootstrap.sh 가 끝났는지 확인(.venv/bin/python 이 있음). 없으면 실행하되 Homebrew 설치나 암호가 필요하면
   멈추고 사용자에게 터미널에서 칠 명령을 한 줄씩 알려 줘.
2. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m "not windows and not slow and not timing"
   실패를 전부 고쳐. Windows 동작은 바꾸지 말 것(맥 분기는 platform.is_mac() / platform.backend() 안에서만).
3. .venv/bin/python -m pytest tests/test_mac_real.py -q
   화면 기록 권한이 없으면 사용자에게 "시스템 설정 > 개인정보 보호 및 보안 > 화면 기록에서 Paseo(또는 터미널)를 켜고,
   Paseo 를 Cmd+Q 로 완전히 종료한 뒤 다시 열기"를 안내하고 기다려. 손쉬운 사용 권한도 같은 식.
4. .venv/bin/python run_capture.py --selftest 가 OK 를 찍을 때까지 고쳐.
5. .venv/bin/python run_capture.py 로 앱을 띄우고(메뉴 막대 아이콘), 설계서 §9 수동 체크리스트를 한 항목씩 사용자에게
   시키고 결과를 받아 고쳐. 예상 걸림: 오버레이가 메뉴 막대까지 덮는지(NSWindow level), scroll.exclude_from_capture 의
   winId→NSView, Retina 에서 mss 크기, Carbon 단축키 수신(Shift+Cmd+2), 키체인 프롬프트, 메뉴 막대 아이콘·메뉴,
   붙여넣기(미리보기·Keynote·메모).
6. ./build.sh — dist/CaptureTool.app 과 installer/Output/CaptureTool-<v>-mac.dmg 가 나오는지, dmg 의 앱을 응용 프로그램
   폴더로 끌어 넣고 우클릭>열기 로 실행되는지 사용자와 확인.
7. 고친 것마다 테스트 먼저, docs/bugs.md(버그만), docs/test-cases.md, 필요하면 guide.py / USER_GUIDE, 커밋·푸시.
   작은 단위로 자주 커밋.
8. 전부 되면 capture_tool/__init__.py 를 0.10.0 으로 올리고 docs/release-notes/v0.10.0.md 를 마무리해 보고해.
   태그 v0.10.0 과 푸시는 사용자가 "진행"이라고 한 뒤에만(CI 가 Windows exe 2종 + 맥 dmg 를 릴리스에 올림).

규칙: 삭제·되돌릴 수 없는 동작은 매번 승인. 임시 파일은 $TMPDIR 아래. 한국어로 짧게 보고. 사용자는 맥이 서툴다 —
사용자가 할 일은 "어디를 눌러 무엇을 하는지" 한 줄씩.
```

## 3. 진행 중 사람이 해 줄 일

| 에이전트가 말하면 | 할 것 |
|---|---|
| "화면 기록 권한을 켜 주세요" | 시스템 설정 > 개인정보 보호 및 보안 > 화면 기록 → **Paseo**(터미널에서 돌리면 **터미널**) 켜기 → Paseo `Cmd + Q` → 다시 열기 → 에이전트에 "켰어" |
| "손쉬운 사용 권한" | 같은 곳의 **손쉬운 사용** 에서 Paseo 켜기 → 재시작 |
| "Shift+Cmd+2 눌러 보세요", "붙여넣어 보세요" | 해 보고 결과를 그대로 말하기(안 되면 무엇이 보였는지) |
| "키체인 접근 허용" 창 | **항상 허용** |
| "커밋/푸시할게요" | 그냥 두면 됨(승인 불필요). 삭제 명령 확인 창이 뜨면 대상 경로를 읽고 허용/거절 |
| "태그 v0.10.0 올릴까요" | 원하면 `진행` |

Paseo 의 **Changes** 탭에서 바뀐 파일을, **New terminal** 에서 직접 명령을 볼 수 있습니다. `paseo.json` 의 스크립트
(`setup`, `test`, `test-mac-real`, `selftest`, `app`, `build`)는 Paseo 가 버튼으로 보여 줍니다.

## 4. 끝난 뒤

- 태그 `v0.10.0` 을 올리면 GitHub Actions 가 Windows 설치 파일 2종과 `CaptureTool-0.10.0-mac.dmg` 를 capture-tool 과
  capture_dist 의 릴리스에 올립니다(맥 잡은 `macos-latest`, 약 20분).
- 맥 설치: dmg → 응용 프로그램으로 끌기 → 우클릭 > 열기 → 화면 기록 권한 → 메뉴 막대 아이콘 → `Shift + Cmd + 2`.
- Windows PC 설치는 그쪽에서 버전마다 승인 뒤에만(기존 규칙).

## 5. 막히면

- 에이전트에 에러 메시지를 그대로 붙입니다(터미널 글자를 드래그해 `Cmd + C`).
- Paseo 없이도 됩니다: 터미널에서 `cd ~/capture-tool && claude` 뒤 2장의 프롬프트를 붙이면 같은 작업.
- Paseo 자체 문제(연결·제공자): Paseo 의 Settings > About / Providers > Diagnostic, 문서 https://paseo.sh/docs/troubleshooting
