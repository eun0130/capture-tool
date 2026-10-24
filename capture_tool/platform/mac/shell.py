"""macOS: open a folder or file with its app, show a file in the Finder, open a web/mail link -
all through `open`."""
from __future__ import annotations

import subprocess


def open_path(path, runner=None) -> None:
    try:
        (runner or subprocess.Popen)(["open", str(path)])
    except OSError:
        pass


def reveal(path, runner=None) -> None:
    try:
        (runner or subprocess.Popen)(["open", "-R", str(path)])
    except OSError:
        pass


def open_url(url: str, runner=None) -> bool:
    """The default browser (https) or mail app (mailto:); other schemes are refused."""
    if not url.startswith(("https://", "mailto:")):
        return False
    try:
        (runner or subprocess.Popen)(["open", url])
        return True
    except OSError:
        return False
