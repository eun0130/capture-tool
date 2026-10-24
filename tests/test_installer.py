"""Installer: an update first clears the old program files it is about to replace (files of
earlier versions that are no longer used, e.g. the old Latin OCR model), and never touches the
user's own data (settings, address book, logs, downloaded models live elsewhere)."""
import re
from pathlib import Path

ISS = Path(__file__).resolve().parents[1] / "installer" / "CaptureTool.iss"


def _section(name: str) -> list[str]:
    text = ISS.read_text(encoding="utf-8")
    m = re.search(rf"^\[{name}\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    return [l.strip() for l in (m.group(1) if m else "").splitlines() if l.strip() and not l.strip().startswith(";")]


def test_INST_01_update_clears_only_the_old_program_files():
    lines = _section("InstallDelete")
    assert lines == ['Type: filesandordirs; Name: "{app}\\_internal"'], lines


def test_INST_02_nothing_outside_the_program_folder_is_deleted():
    text = ISS.read_text(encoding="utf-8")
    for sec in ("InstallDelete", "UninstallDelete"):
        for l in _section(sec):
            name = re.search(r'Name:\s*"([^"]+)"', l).group(1)
            assert name.startswith("{app}\\") and ".." not in name, l
    assert "{userappdata}" not in text and "{localappdata}\\CaptureTool" not in text


def test_INST_03_user_data_lives_outside_the_program_folder(monkeypatch, tmp_path):
    from capture_tool.app import main
    from capture_tool.core import model_store as ms
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    program = tmp_path / "Local" / "Programs" / "CaptureTool"
    for p in (main.data_dir(), main.log_dir(), ms.user_root()):
        assert program not in p.parents and p != program, p


def test_INST_10_mac_bundle_build_script_and_ci_job():
    """The Mac build: a menu-bar .app with the permission texts (packaging/capture_tool.spec BUNDLE),
    build.sh making CaptureTool-<v>-mac.dmg + .sha256 with an ad-hoc signature, a macos CI job
    uploading them into the releases, and no Windows-only module in the Mac bundle."""
    ROOT = ISS.parents[1]
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    assert 'BUNDLE(' in spec and 'name="CaptureTool.app"' in spec and 'bundle_identifier="com.capturetool.app"' in spec
    for key in ("LSUIElement", "NSScreenCaptureUsageDescription", "NSAppleEventsUsageDescription",
                "CFBundleShortVersionString", "LSMinimumSystemVersion"):
        assert key in spec, key
    assert '"capture_tool.platform.kakao"' in spec.split("MAC_EXCLUDES")[1] and "win32com" in spec.split("MAC_EXCLUDES")[1]
    sh = (ROOT / "build.sh").read_text(encoding="utf-8")
    assert "codesign --force --deep -s -" in sh and "hdiutil create" in sh and "-mac.dmg" in sh and "shasum -a 256" in sh
    assert "capture_tool.spec" in sh and "--skip-tests" in sh
    yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "runs-on: macos-latest" in yml and "./build.sh --skip-tests" in yml
    assert "not windows and not mac" in yml and "--repo eun0130/capture_dist --clobber" in yml
    assert re.search(r"name: CaptureTool-mac", yml)
    icon = (ROOT / "tools" / "make_icon.py").read_text(encoding="utf-8")
    assert "iconutil" in icon and "app.icns" in icon
