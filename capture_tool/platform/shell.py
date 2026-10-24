"""Windows: open a folder or file with its program, show a file in Explorer, open a web/mail link."""
from __future__ import annotations

import os
import subprocess


def open_path(path, runner=None) -> None:
    try:
        (runner or os.startfile)(str(path))
    except OSError:
        pass


def reveal(path, runner=None) -> None:
    try:
        (runner or subprocess.Popen)(["explorer", "/select,", str(path)])
    except OSError:
        pass


def open_url(url: str, runner=None) -> bool:
    """The default browser (https) or mail app (mailto:); other schemes are refused."""
    if not url.startswith(("https://", "mailto:")):
        return False
    try:
        (runner or os.startfile)(url)
        return True
    except OSError:
        return False
