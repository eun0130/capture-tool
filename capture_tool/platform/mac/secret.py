"""Secrets (the AI key) in the login Keychain through the `security` tool: `protect` stores the
text under a fresh account name and returns that name (what the settings file keeps);
`unprotect` reads it back. Nothing secret is ever written to the settings file."""
from __future__ import annotations

import subprocess
import uuid

SERVICE = "CaptureTool"


class SecretError(Exception):
    pass


def _run(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["security", *args], capture_output=True, check=False)
    except OSError as e:
        raise SecretError(str(e)) from e


def protect(text: str) -> str:
    account = f"key-{uuid.uuid4().hex}"
    r = _run(["add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", text])
    if r.returncode:
        raise SecretError(r.stderr.decode(errors="replace").strip() or "키체인에 저장하지 못했습니다.")
    return account


def unprotect(blob: str) -> str:
    if not blob.startswith("key-"):
        raise SecretError("키체인 항목이 아닙니다.")
    r = _run(["find-generic-password", "-s", SERVICE, "-a", blob, "-w"])
    if r.returncode:
        raise SecretError("키체인에서 읽지 못했습니다.")
    return r.stdout.decode(errors="replace").rstrip("\n")


def forget(blob: str) -> None:
    """Remove a stored item (tests, replacing a key)."""
    _run(["delete-generic-password", "-s", SERVICE, "-a", blob])
