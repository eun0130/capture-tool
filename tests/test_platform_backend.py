"""One platform package, two backends: app code asks `platform.backend()` for screen / clipboard /
hotkey / windows / scroll / startup / secret / shell and never names an OS module. CAPTURE_PLATFORM
(not in a frozen build) forces the choice for tests."""
import re
import sys
from pathlib import Path

from capture_tool import platform as pf

ROOT = Path(__file__).resolve().parents[1]


def test_PB_01_the_backend_follows_the_os_and_CAPTURE_PLATFORM(monkeypatch):
    monkeypatch.delenv("CAPTURE_PLATFORM", raising=False)
    pf.use(None)
    assert pf.name() == sys.platform
    assert pf.is_mac() == (sys.platform == "darwin")
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert pf.is_mac() and pf.backend() is pf.MAC
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert not pf.is_mac() and pf.backend() is pf.WINDOWS
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert pf.name() == sys.platform                      # an installed build ignores the variable


def test_PB_02_windows_backend_maps_names_to_the_existing_modules(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    b = pf.backend()
    from capture_tool.platform import screen, shell, win_clipboard, win_hotkey
    assert b.clipboard is win_clipboard and b.hotkey is win_hotkey and b.screen is screen and b.shell is shell


def test_PB_03_mac_backend_modules_import_on_any_os(monkeypatch):
    """The Mac modules import pyobjc lazily inside functions, so the package loads on Windows."""
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    b = pf.backend()
    for n in ("screen", "clipboard", "hotkey", "windows", "scroll", "startup", "secret", "shell"):
        assert getattr(b, n).__name__ == f"capture_tool.platform.mac.{n}"


def test_PB_04_use_swaps_the_backend_for_tests():
    class Fake:
        pass
    before = pf.use(Fake)
    try:
        assert pf.backend() is Fake
    finally:
        pf.use(before)
    assert pf.backend() is not Fake


def test_PB_05_shell_opens_paths_and_urls_through_injected_runners(tmp_path):
    from capture_tool.platform import shell
    ran = []
    shell.open_path(tmp_path, runner=lambda p: ran.append(("start", str(p))))
    shell.reveal(tmp_path / "a.png", runner=lambda cmd: ran.append(("popen", cmd)))
    assert shell.open_url("https://x", runner=lambda u: ran.append(("url", u))) is True
    assert shell.open_url("file:///etc", runner=lambda u: ran.append(("url", u))) is False
    assert ran[0] == ("start", str(tmp_path)) and ran[1][1][:2] == ["explorer", "/select,"] and ran[2] == ("url", "https://x")
    shell.open_path(tmp_path, runner=lambda p: (_ for _ in ()).throw(OSError("no")))      # failures are swallowed


def test_PB_06_app_layer_never_names_an_os_module():
    """Office / KakaoTalk / Lens / security_software / printing imports stay (hidden through
    edition.excluded() on the Mac, or Qt-only); the OS services go through the backend."""
    bad = []
    for f in (ROOT / "capture_tool" / "app").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"from \.\.platform(?:\.(\w+))? import ([\w, ]+)", src):
            names = {m.group(1)} if m.group(1) else {n.strip() for n in m.group(2).split(",")}
            if names & {"screen", "win_clipboard", "win_hotkey", "windows", "scroll", "startup", "secret", "shell"}:
                bad.append(f"{f.name}: {m.group(0)}")
        if "os.startfile" in src or '"explorer"' in src:
            bad.append(f"{f.name}: os.startfile/explorer")
    assert bad == [], bad
