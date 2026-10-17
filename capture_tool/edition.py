"""Which edition this is. 집용 "home" has everything; 회사용 "work" has no KakaoTalk and no
web mail at all (no button, no guide page, no settings, no sender), for PCs where they must not
exist. The work installer is built
with capture_tool/edition.txt saying "work" (build.ps1 -Edition work); the source tree carries
no such file, so a developer run is the home edition. CAPTURE_EDITION in the environment
overrides the file (tests, trying the work edition from source) - but never in an installed
(frozen) build, so a work PC cannot get the features back by setting a variable; the work
build also leaves the KakaoTalk and mail modules out (packaging/capture_tool.spec)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOME, WORK = "home", "work"
EXCLUDED_AT_WORK = ("kakao", "mail")      # bar buttons (and their code paths) the work edition has not got
_MARKER = Path(__file__).with_name("edition.txt")
_file_edition: str | None = None


def _from_file() -> str:
    global _file_edition
    if _file_edition is None:
        try:
            text = _MARKER.read_text(encoding="utf-8").strip().lower()
        except OSError:
            text = ""
        _file_edition = WORK if text == WORK else HOME
    return _file_edition


def reset() -> None:
    """Forget the marker file's answer (tests swap the file)."""
    global _file_edition
    _file_edition = None


def current() -> str:
    if not getattr(sys, "frozen", False):            # the installed build is what its marker says, full stop
        env = os.environ.get("CAPTURE_EDITION", "").strip().lower()
        if env in (HOME, WORK):
            return env
    return _from_file()


def is_work() -> bool:
    return current() == WORK


def excluded() -> tuple[str, ...]:
    """The buttons this edition leaves out."""
    return EXCLUDED_AT_WORK if is_work() else ()


def has(name: str) -> bool:
    return name not in excluded()


def has_kakao() -> bool:
    return has("kakao")


def title() -> str:
    return "캡처 도구 (회사용)" if is_work() else "캡처 도구"
