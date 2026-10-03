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
