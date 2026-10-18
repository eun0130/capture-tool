"""Updating the installed app. Where a newer version comes from: the GitHub Releases of this
edition's own repository (집용 eun0130/capture-tool, 회사용 eun0130/capture_work), another
"owner/name", or a folder a company keeps installers in (a share path works). The installer is
downloaded next to the settings, its SHA-256 checked against the release's .sha256 file (a
company folder may omit it), then run silently a few seconds after the app has quit; the
installer restarts the app (/UPDATE=1). No network code runs here without being asked:
every fetch is a plain function the caller may replace."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPOS = {"home": "eun0130/capture-tool", "work": "eun0130/capture_work"}
INSTALLER = {"home": "CaptureTool-Setup-{v}.exe", "work": "CaptureTool-Work-Setup-{v}.exe"}
_PATTERN = {"home": re.compile(r"^CaptureTool-Setup-(\d+\.\d+\.\d+)\.exe$"),
            "work": re.compile(r"^CaptureTool-Work-Setup-(\d+\.\d+\.\d+)\.exe$")}
TIMEOUT = 8.0
USER_AGENT = "CaptureTool-updater"
CHECK_EVERY_HOURS = 24


class UpdateError(Exception):
    """Could not check / download / verify - a message for the person."""


@dataclass
class Update:
    version: str
    name: str                  # the installer's file name
    installer_url: str         # https://… or a file path (folder source)
    sums_url: str | None       # the .sha256 beside it (None: a company folder without one)
    size: int
    notes: str


def parse_version(tag: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def _fetch(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fetch_to(url: str, dest: Path, progress: Callable[[int, int], None], timeout: float = TIMEOUT) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            progress(done, total)


def _from_folder(current: str, edition: str, folder: Path) -> Update | None:
    pat = _PATTERN[edition]
    best = None
    try:
        names = [p.name for p in folder.iterdir() if p.is_file()]
    except OSError:
        return None                                  # not there / not reachable: simply no update
    for name in names:
        m = pat.match(name)
        if m and newer(m.group(1), current) and (best is None or newer(m.group(1), best[0])):
            best = (m.group(1), name)
    if best is None:
        return None
    version, name = best
    path = folder / name
    sums = folder / (name + ".sha256")
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return Update(version, name, str(path), str(sums) if sums.exists() else None, size, "")


def _from_github(current: str, edition: str, repo: str, fetch: Callable) -> Update | None:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        data = json.loads(fetch(url, timeout=TIMEOUT).decode("utf-8"))
    except (OSError, ValueError) as e:
        if isinstance(e, ValueError):
            return None                              # not a release page: nothing to offer
        raise UpdateError("업데이트 확인 실패 — 인터넷 연결을 확인하세요.") from e
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name") or "")
    v = parse_version(tag)
    if v is None or not newer(tag, current):
        return None
    version = ".".join(str(x) for x in v)
    name = INSTALLER[edition].format(v=version)
    assets = {a.get("name"): a for a in data.get("assets") or [] if isinstance(a, dict)}
    inst = assets.get(name)
    if inst is None:
        return None
    sums = assets.get(name + ".sha256")
    if sums is None:
        raise UpdateError("업데이트 파일에 검증 정보(.sha256)가 없어 받지 않습니다.")
    return Update(version, name, str(inst.get("browser_download_url") or ""), str(sums.get("browser_download_url") or ""),
                  int(inst.get("size") or 0), str(data.get("body") or ""))


def check(current: str, edition: str, source: str = "", fetch: Callable | None = None) -> Update | None:
    """The newer version on offer, or None. `source`: "" = this edition's GitHub repository,
    "owner/name" = another one, anything else = a folder of installers (UNC paths welcome).
    Raises UpdateError when the network check itself failed."""
    edition = edition if edition in REPOS else "home"
    source = (source or "").strip()
    if source and not re.fullmatch(r"[\w.-]+/[\w.-]+", source):
        return _from_folder(current, edition, Path(source))
    return _from_github(current, edition, source or REPOS[edition], fetch or _fetch)


def verify(path: Path, sums_text: str) -> bool:
    """True when sums_text ("<sha256>  <name>" or "<sha256> *<name>", any line) has this file's hash."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].lower() == digest and parts[1].lstrip("*") == path.name:
            return True
    return False


def download(u: Update, into: Path, fetch: Callable | None = None, fetch_to: Callable | None = None,
             progress: Callable[[int, int], None] | None = None) -> Path:
    """The installer, downloaded (or copied from the folder) into `into` and verified."""
    fetch, fetch_to = fetch or _fetch, fetch_to or _fetch_to
    progress = progress or (lambda done, total: None)
    into.mkdir(parents=True, exist_ok=True)
    dest = into / u.name
    try:
        src = Path(u.installer_url)
        if not u.installer_url.startswith(("http://", "https://")) and src.is_file():
            data = src.read_bytes()
            dest.write_bytes(data)
            progress(len(data), len(data))
        else:
            fetch_to(u.installer_url, dest, progress, timeout=60.0)
    except OSError as e:
        _drop(dest)
        raise UpdateError("업데이트 파일을 받지 못했습니다 — 인터넷 연결을 확인하세요.") from e
    if u.sums_url:
        try:
            s = Path(u.sums_url)
            text = s.read_text(encoding="utf-8") if not u.sums_url.startswith(("http://", "https://")) and s.is_file() \
                else fetch(u.sums_url, timeout=TIMEOUT).decode("utf-8", "replace")
        except OSError as e:
            _drop(dest)
            raise UpdateError("업데이트 검증 정보를 받지 못했습니다.") from e
        if not verify(dest, text):
            _drop(dest)
            raise UpdateError("받은 업데이트 파일이 검증에 실패해 설치하지 않습니다. 나중에 다시 시도하세요.")
    return dest


def _drop(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


DETACHED_PROCESS, CREATE_NO_WINDOW = 0x00000008, 0x08000000


def launch_installer(path: Path, runner: Callable | None = None) -> None:
    """Run the installer silently a few seconds from now (the app quits meanwhile); it restarts
    the app itself (/UPDATE=1 - installer/CaptureTool.iss)."""
    cmd = ["cmd.exe", "/c", f'ping -n 4 127.0.0.1 >nul & "{path}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES /UPDATE=1']
    (runner or subprocess.Popen)(cmd, creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW, close_fds=True)
