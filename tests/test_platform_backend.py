"""One platform package, two backends: app code asks `platform.backend()` for screen / clipboard /
hotkey / windows / scroll / startup / secret / shell and never names an OS module. CAPTURE_PLATFORM
(not in a frozen build) forces the choice for tests."""
import re
import sys
from pathlib import Path

import pytest

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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API / Windows fonts")
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


def test_PB_07_every_module_the_backend_loads_by_name_is_bundled_on_its_os():
    """v0.10.0 (Windows): the installed app stopped at start - "No module named
    capture_tool.platform.win_hotkey". backend() imports its modules by name (importlib), which
    PyInstaller cannot see; each OS's list in the spec must name every one of them (the Mac had the
    same failure, MAC-13)."""
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    hidden_expr = spec.split("hiddenimports=")[1].split(")")[0]
    for listname, backend in (("WIN_BACKEND", pf.WINDOWS), ("MAC_BACKEND", pf.MAC)):
        listed = spec.split(f"{listname} = ")[1].split("]")[0]
        for mod in sorted(set(backend._names.values())):
            full = f"{backend._package}.{mod}"
            assert f'"{full}"' in listed, f"{full} missing from {listname} in packaging/capture_tool.spec"
    assert "WIN_HIDDEN + WIN_BACKEND" in hidden_expr and "MAC_HIDDEN + MAC_BACKEND" in hidden_expr


def test_PB_08_check_backend_loads_every_os_module_and_reports_it(capsys):
    """The build scripts run the built app with --check-backend before packaging: a module the bundle
    lacks then stops the build instead of the person's installed app (v0.10.0, win_hotkey)."""
    from capture_tool.app import main
    assert main.main(["CaptureTool", "--check-backend"]) == 0
    assert "BACKEND OK" in capsys.readouterr().out
    broken = pf.Backend("capture_tool.platform", {n: "no_such_module" for n in pf._NAMES})
    before = pf.use(broken)
    try:
        assert main.check_backend() == 1
        assert "BACKEND MISSING" in capsys.readouterr().out
    finally:
        pf.use(before)


def test_PB_09_check_backend_also_runs_each_modules_own_check(capsys):
    """The Windows screen module needs dxcam (DXGI, BUG-142) in the bundle; its self_check imports it,
    so a build without it stops at --check-backend instead of capturing white again."""
    import types
    from capture_tool.app import main
    good = types.SimpleNamespace(self_check=lambda: [])
    bad = types.SimpleNamespace(self_check=lambda: ["dxcam: No module named 'dxcam'"])
    fake = types.SimpleNamespace(**{n: good for n in pf._NAMES})
    fake.screen = bad
    before = pf.use(fake)
    try:
        assert main.check_backend() == 1
        assert "dxcam" in capsys.readouterr().out
    finally:
        pf.use(before)
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    assert 'collect_submodules("dxcam")' in spec and '"comtypes"' in spec


def test_PB_10_both_screens_offer_the_recording_grab_and_the_mouse_reader():
    """Recording reads the screen and the mouse on its own thread: each OS hands over ready-made
    functions (built on the GUI thread, where the Mac asks Qt for the display scale)."""
    import ast
    for path in ("capture_tool/platform/screen.py", "capture_tool/platform/mac/screen.py"):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        fns = {n.name: [a.arg for a in n.args.args] for n in tree.body if isinstance(n, ast.FunctionDef)}
        for fn in ("recording_grabber", "mouse_reader"):
            assert fns.get(fn) == ["rect"], (path, fn)


def test_PB_11_the_recorders_check_their_own_parts():
    """--check-backend runs each module's self_check: the Mac writer needs AVFoundation / CoreMedia /
    CoreAudio / Quartz in the bundle. The Windows writer only uses ctypes; Media Foundation itself is
    part of Windows (missing on Windows Server, where the build runs, so it is not a build error)."""
    import ast
    for path, needs in (("capture_tool/platform/mac/recorder.py", ("AVFoundation", "CoreMedia", "CoreAudio", "Quartz")),
                        ("capture_tool/platform/mf_recorder.py", ())):
        src = (ROOT / path).read_text(encoding="utf-8")
        fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "self_check")
        body = ast.get_source_segment(src, fn)
        assert all(n in body for n in needs), path
