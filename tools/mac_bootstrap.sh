#!/bin/sh
# 맥 개발 환경을 한 번에 준비한다: Homebrew -> python 3.12 / git / gh -> .venv -> 의존성 -> 모델 -> Claude Code -> 테스트.
# 몇 번 다시 실행해도 안전하다(이미 있는 것은 건너뜀). 사람이 터미널에서 실행한다 - Homebrew 설치가 암호를 묻는다.
# 사용:  ~/capture-tool/tools/mac_bootstrap.sh      끝나면 다음 할 일을 알려 준다 (docs/MAC_HANDOFF.md).
set -e
cd "$(dirname "$0")/.."
step() { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }
[ "$(uname -s)" = Darwin ] || { echo "맥에서만 실행하는 스크립트입니다."; exit 1; }
[ "$(uname -m)" = arm64 ] || echo "주의: Apple Silicon이 아닙니다. build.sh 는 arm64 기준입니다."

if ! command -v brew >/dev/null 2>&1; then
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    else
        step "Homebrew 설치 - RETURN 을 누르고, 물으면 맥 로그인 암호를 입력하세요 (입력해도 글자는 안 보입니다)"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)"
        grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
    fi
fi

step "python 3.12, git, gh"
for f in python@3.12 git gh; do brew list "$f" >/dev/null 2>&1 || brew install "$f"; done
PY="$(brew --prefix python@3.12)/bin/python3.12"

step "가상환경 + 의존성 (.venv) - 처음에는 몇 분"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev]"

step "OCR·번역 모델 받기 (처음 한 번, 수백 MB)"
.venv/bin/python tools/fetch_models.py

step "Claude Code"
if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    curl -fsSL https://claude.ai/install.sh | bash
else
    echo "이미 설치됨"
fi

step "테스트 (Windows 전용·실제 맥 API 제외, 몇 분)"
if QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -m "not windows and not mac and not slow and not timing" 2>&1 | tail -3; then
    echo "테스트 끝"
else
    echo "실패한 테스트가 있습니다 - 맥 세션의 에이전트가 고칩니다(예상된 다음 단계)."
fi

step "준비 끝"
cat <<'EOF'
다음 (docs/MAC_HANDOFF.md 의 1-5 부터):
  1. 이 터미널에서   claude   를 실행해 로그인하고  /exit
  2. Paseo 설치:    brew install --cask paseo     (또는 https://paseo.sh/download 의 Apple Silicon)
  3. Paseo 에서 ~/capture-tool 을 프로젝트로 열고, Claude 에이전트에 docs/MAC_HANDOFF.md 의 프롬프트를 붙이기
EOF
