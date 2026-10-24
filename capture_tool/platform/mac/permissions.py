"""Screen Recording (capturing, window names) and Accessibility (scroll events, cursor moves)
must be granted in System Settings; this module only asks, reports and opens the right pane."""
from __future__ import annotations

import subprocess

PANES = {"screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
         "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"}
MESSAGES = {"screen": "시스템 설정 > 개인정보 보호 및 보안 > 화면 기록에서 캡처 도구를 켜고 다시 실행하세요.",
            "accessibility": "스크롤 캡처는 시스템 설정 > 개인정보 보호 및 보안 > 손쉬운 사용에서 캡처 도구를 켜야 합니다."}


def screen_recording() -> bool:
    from Quartz import CGPreflightScreenCaptureAccess
    return bool(CGPreflightScreenCaptureAccess())


def request_screen_recording() -> bool:
    """Shows the system dialog once; True if already granted."""
    from Quartz import CGRequestScreenCaptureAccess
    return bool(CGRequestScreenCaptureAccess())


def accessibility() -> bool:
    from ApplicationServices import AXIsProcessTrusted
    return bool(AXIsProcessTrusted())


def open_settings(pane: str, runner=None) -> None:
    (runner or subprocess.Popen)(["open", PANES[pane]])
