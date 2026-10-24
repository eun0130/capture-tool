"""Updating: the app learns of a newer release (GitHub Releases of its own edition's repository,
or a folder a company points it at), downloads the installer, checks its SHA-256 against the
release's .sha256 file, runs the installer silently and restarts. Nothing of it needs a network
here: fetches are injected."""
import hashlib
import json
from pathlib import Path

import pytest

from capture_tool import __version__
from capture_tool.core import update

ROOT = Path(__file__).resolve().parents[1]


def _release(tag: str, names: list[str]) -> bytes:
    assets = [{"name": n, "browser_download_url": f"https://dl.example/{tag}/{n}", "size": 1000 + i} for i, n in enumerate(names)]
    return json.dumps({"tag_name": tag, "body": "고침 목록", "assets": assets}).encode("utf-8")


def test_UP_01_versions_compare_as_numbers_not_strings():
    assert update.parse_version("v0.8.30") == (0, 8, 30) and update.parse_version("0.10.2") == (0, 10, 2)
    assert update.parse_version("latest") is None and update.parse_version("v1.2") is None
    assert update.newer("v0.8.30", "0.8.29") and update.newer("v0.9.0", "0.8.99") and not update.newer("v0.8.29", "0.8.29")
    assert not update.newer("junk", "0.8.29")


def test_UP_02_check_finds_the_editions_own_installer_on_github():
    seen = []

    def fetch(url, timeout=0):
        seen.append(url)
        return _release("v9.9.9", ["CaptureTool-Setup-9.9.9.exe", "CaptureTool-Setup-9.9.9.exe.sha256",
                                   "CaptureTool-Work-Setup-9.9.9.exe", "CaptureTool-Work-Setup-9.9.9.exe.sha256"])
    u = update.check("0.8.29", "home", fetch=fetch)
    assert seen == ["https://api.github.com/repos/eun0130/capture_dist/releases/latest"]
    assert u.version == "9.9.9" and u.installer_url.endswith("/CaptureTool-Setup-9.9.9.exe")
    assert u.sums_url.endswith("/CaptureTool-Setup-9.9.9.exe.sha256") and u.notes == "고침 목록" and u.size == 1000
    w = update.check("0.8.29", "work", fetch=fetch)
    assert seen[-1] == "https://api.github.com/repos/eun0130/capture_work/releases/latest"
    assert w.installer_url.endswith("/CaptureTool-Work-Setup-9.9.9.exe") and w.name == "CaptureTool-Work-Setup-9.9.9.exe"
    assert update.check("9.9.9", "home", fetch=fetch) is None                      # already current
    assert update.check("0.8.29", "home", source="someone/else", fetch=fetch) is not None
    assert seen[-1] == "https://api.github.com/repos/someone/else/releases/latest"


def test_UP_03_check_tolerates_a_release_without_the_installer_and_network_errors():
    assert update.check("0.8.29", "home", fetch=lambda u, timeout=0: _release("v9.9.9", ["README.md"])) is None
    assert update.check("0.8.29", "home", fetch=lambda u, timeout=0: b"not json") is None

    def boom(url, timeout=0):
        raise OSError("offline")
    with pytest.raises(update.UpdateError):
        update.check("0.8.29", "home", fetch=boom)
    with pytest.raises(update.UpdateError):
        update.check("0.8.29", "home", fetch=lambda u, timeout=0: _release("v9.9.9", ["CaptureTool-Setup-9.9.9.exe"]))   # no .sha256: refused


def test_UP_04_a_company_folder_is_a_source_too(tmp_path):
    (tmp_path / "CaptureTool-Work-Setup-0.8.30.exe").write_bytes(b"old")
    new = tmp_path / "CaptureTool-Work-Setup-0.8.31.exe"
    new.write_bytes(b"newer installer")
    (tmp_path / "CaptureTool-Setup-0.9.0.exe").write_bytes(b"home edition: not ours")
    u = update.check("0.8.29", "work", source=str(tmp_path))
    assert u.version == "0.8.31" and u.installer_url == str(new) and u.sums_url is None
    assert update.check("0.8.31", "work", source=str(tmp_path)) is None
    assert update.check("0.8.29", "work", source=str(tmp_path / "missing")) is None   # a folder that is not there: no update, no error
    (tmp_path / "CaptureTool-Work-Setup-0.8.31.exe.sha256").write_text(
        hashlib.sha256(b"newer installer").hexdigest() + " *CaptureTool-Work-Setup-0.8.31.exe\n", encoding="utf-8")
    u = update.check("0.8.29", "work", source=str(tmp_path))
    assert u.sums_url == str(tmp_path / "CaptureTool-Work-Setup-0.8.31.exe.sha256")


def test_UP_05_download_verifies_the_hash_and_refuses_a_tampered_file(tmp_path):
    body = b"x" * 5000
    good = hashlib.sha256(body).hexdigest()
    files = {"https://dl/CaptureTool-Setup-1.0.0.exe": body,
             "https://dl/CaptureTool-Setup-1.0.0.exe.sha256": (good + "  CaptureTool-Setup-1.0.0.exe\n").encode()}

    def fetch(url, timeout=0):
        return files[url]

    def fetch_to(url, dest, progress, timeout=0):
        data = files[url]
        for i in range(0, len(data), 2000):
            progress(min(i + 2000, len(data)), len(data))
        dest.write_bytes(data)
    u = update.Update("1.0.0", "CaptureTool-Setup-1.0.0.exe", "https://dl/CaptureTool-Setup-1.0.0.exe",
                      "https://dl/CaptureTool-Setup-1.0.0.exe.sha256", len(body), "")
    seen = []
    path = update.download(u, tmp_path, fetch=fetch, fetch_to=fetch_to, progress=lambda d, t: seen.append((d, t)))
    assert path.read_bytes() == body and path.name == "CaptureTool-Setup-1.0.0.exe" and seen[-1] == (5000, 5000)
    files["https://dl/CaptureTool-Setup-1.0.0.exe.sha256"] = ("0" * 64 + "  CaptureTool-Setup-1.0.0.exe\n").encode()
    with pytest.raises(update.UpdateError) as e:
        update.download(u, tmp_path, fetch=fetch, fetch_to=fetch_to)
    assert "검증" in str(e.value) and not (tmp_path / "CaptureTool-Setup-1.0.0.exe").exists()    # the bad file is not kept
    assert update.verify(path if path.exists() else tmp_path / "x", good + " *other-name.exe") is False


def test_UP_06_the_installer_runs_silently_after_the_app_has_quit(tmp_path):
    exe = tmp_path / "CaptureTool-Setup-1.0.0.exe"
    exe.write_bytes(b"")
    ran = []
    update.launch_installer(exe, runner=lambda cmd, **kw: ran.append((cmd, kw)))
    cmd, kw = ran[0]
    line = " ".join(cmd)
    assert "/VERYSILENT" in line and "/NORESTART" in line and "/UPDATE=1" in line and str(exe) in line
    assert "ping" in line                                                        # a few seconds for the app to exit first
    assert kw.get("creationflags", 0) & 0x8                                      # DETACHED_PROCESS: survives the app's exit


def test_UP_07_the_installer_restarts_the_app_after_an_update_and_the_release_ships_hashes():
    iss = (ROOT / "installer" / "CaptureTool.iss").read_text(encoding="utf-8")
    assert "UPDATE" in iss and "IsUpdate" in iss                                 # [Run] ... Check: IsUpdate
    yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "Get-FileHash" in yml and ".sha256" in yml
    ps = (ROOT / "tools" / "publish_work.ps1").read_text(encoding="utf-8")
    assert ".sha256" in ps
    assert update.REPOS == {"home": "eun0130/capture_dist", "work": "eun0130/capture_work", "mac": "eun0130/capture_dist"}
    assert update.parse_version(__version__) is not None


def test_UP_08_the_tray_offers_the_new_version_and_installs_it_on_request(qt_app, tmp_path, monkeypatch):
    from capture_tool.app import main
    monkeypatch.setattr(main, "data_dir", lambda: tmp_path)
    tray = main.TrayApp(qt_app, selftest=True)
    try:
        u = update.Update("9.9.9", "CaptureTool-Setup-9.9.9.exe", "https://dl/x.exe", "https://dl/x.exe.sha256", 10, "새 기능")
        monkeypatch.setattr(update, "check", lambda *a, **k: u)
        tray.check_update(manual=True, wait=True)
        assert tray.available is u
        texts = [a.text() for a in tray.menu.actions()]
        assert any("9.9.9" in t and "설치" in t for t in texts) and any("업데이트 확인" in t for t in texts)
        assert tray.settings.update_last != ""
        got = []
        monkeypatch.setattr(update, "download", lambda upd, d, **k: got.append(("download", upd.version)) or (tmp_path / "setup.exe"))
        monkeypatch.setattr(update, "launch_installer", lambda p, **k: got.append(("launch", p.name)) or True)
        monkeypatch.setattr(tray, "_confirm_update", lambda upd: True)
        quit_called = []
        monkeypatch.setattr(tray, "quit", lambda: quit_called.append(True))
        tray.install_update(wait=True)
        assert got == [("download", "9.9.9"), ("launch", "setup.exe")] and quit_called == [True]
        monkeypatch.setattr(update, "check", lambda *a, **k: None)
        tray.check_update(manual=True, wait=True)
        assert tray.available is None and not any("9.9.9" in a.text() for a in tray.menu.actions())
        tray.settings.update_check = False
        assert tray.update_due() is False                                        # switched off: never on its own
    finally:
        tray.hk_window.manager.apply({})
        tray.controller.close_all()
        tray.tray.hide()


def test_UP_10_mac_channel_reads_the_dmg_from_capture_dist(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    assert update.channel("home") == "mac" and update.channel("work") == "mac"
    assert update.REPOS["mac"] == "eun0130/capture_dist"
    assert update.INSTALLER["mac"].format(v="1.2.3") == "CaptureTool-1.2.3-mac.dmg"
    assert update._PATTERN["mac"].match("CaptureTool-1.2.3-mac.dmg").group(1) == "1.2.3"
    assert update._PATTERN["mac"].match("CaptureTool-Setup-1.2.3.exe") is None
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    assert update.channel("work") == "work" and update.channel("home") == "home"


def test_UP_11_on_the_mac_the_dmg_is_opened_and_the_app_stays(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    dmg = tmp_path / "CaptureTool-1.0.0-mac.dmg"
    dmg.write_bytes(b"")
    ran = []
    assert update.launch_installer(dmg, runner=lambda cmd, **kw: ran.append(cmd)) is False
    assert ran == [["open", str(dmg)]]
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    exe = tmp_path / "CaptureTool-Setup-1.0.0.exe"
    exe.write_bytes(b"")
    assert update.launch_installer(exe, runner=lambda cmd, **kw: None) is True


def test_UP_12_the_mac_channel_finds_the_dmg_in_a_folder_and_on_github(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")
    (tmp_path / "CaptureTool-9.9.9-mac.dmg").write_bytes(b"x")
    u = update.check("0.1.0", "mac", str(tmp_path))
    assert u and u.version == "9.9.9" and u.name.endswith("-mac.dmg")
    release = {"tag_name": "v9.9.9", "body": "", "assets": [
        {"name": "CaptureTool-9.9.9-mac.dmg", "browser_download_url": "https://x/d.dmg", "size": 5},
        {"name": "CaptureTool-9.9.9-mac.dmg.sha256", "browser_download_url": "https://x/d.sha256", "size": 70},
        {"name": "CaptureTool-Setup-9.9.9.exe", "browser_download_url": "https://x/s.exe", "size": 5}]}
    u = update.check("0.1.0", "mac", fetch=lambda url, timeout=0: json.dumps(release).encode())
    assert u and u.name == "CaptureTool-9.9.9-mac.dmg" and u.installer_url == "https://x/d.dmg" and u.sums_url == "https://x/d.sha256"
