"""Launch at login through a LaunchAgent (~/Library/LaunchAgents/com.capturetool.app.plist): the
plist runs the app with --tray when the person logs in; removing the file turns it off."""
from __future__ import annotations

from pathlib import Path

LABEL = "com.capturetool.app"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_text(exe_path: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
        <string>--tray</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""


def set_enabled(enabled: bool, exe_path: str, backend=None) -> None:
    p = plist_path()
    if enabled:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(plist_text(exe_path), encoding="utf-8")
    elif p.exists():
        p.unlink()


def is_enabled(backend=None) -> bool:
    return plist_path().exists()
