# 캡처 도구 — 이 리포의 작업 규칙 (모든 OS·세션 공통)

## 사용자와 말투
- 한국어로 짧게. 설명보다 결과. 결정은 먼저 하고 결과만 알린다.
- 사용자는 맥이 서툴다: 사용자가 손으로 할 일은 "어디를 눌러 무엇을 하는지" 한 줄씩 적는다.

## 흐름
테스트 먼저(TDD) → 구현 → 문서(`docs/bugs.md`는 버그만, `docs/test-cases.md`, `docs/release-notes/`,
기능이 바뀌면 `capture_tool/app/guide.py`·`docs/USER_GUIDE.md`·`docs/QUICK_START.md`) → 전체 테스트 → selftest → 커밋 →
태그 `v*`(release.yml) → 배포. 작은 단위로 자주 커밋.

## 승인이 필요한 것
- 삭제·되돌릴 수 없는 동작(`rm`, `git reset --hard`, `git clean`, `git push --force`, 설정 파일 덮어쓰기)은 대상·개수·경로를
  먼저 보이고 사용자 승인 뒤에 실행한다. 한 번의 승인은 그 한 동작에만. 이동·백업으로 되면 그쪽을 먼저 제안.
  `.claude/hooks/confirm-delete.sh`(PreToolUse)가 Bash 패턴을 잡아 묻는다.
- 이 PC에 설치(installer 실행, 앱 교체)와 릴리스(태그·publish)는 사용자가 "진행"이라고 한 뒤에만.
- 임시 파일은 리포 밖(macOS `$TMPDIR`, Windows 스크래치패드). 리포 안으로 `>` 리다이렉트 금지.

## 커밋
영어 conventional commit(feat/fix/build/chore/docs/test). 끝에 세션이 알려 주는 `Co-Authored-By:` 트레일러.

## 구조 규칙
- OS 호출은 전부 `capture_tool.platform.backend()` 경유(테스트 PB-06이 강제). 맥 전용 분기는 `platform.is_mac()`.
  Windows 동작·테스트는 바꾸지 않는다(회사 PC에서 쓰는 빌드).
- 테스트: `pytest -m "not windows and not slow and not timing"`(어디서나), `pytest tests/test_mac_real.py`(맥, 화면 기록 권한),
  `python run_capture.py --selftest`.

## 맥 작업
`docs/MAC_HANDOFF.md`(맥에서 이어서 하는 절차와 에이전트 프롬프트), 설계 `docs/superpowers/specs/2026-10-24-macos-port-design.md`,
계획 `docs/superpowers/plans/2026-10-24-macos-port.md`. 환경 준비는 `tools/mac_bootstrap.sh`, Paseo 스크립트는 `paseo.json`.
