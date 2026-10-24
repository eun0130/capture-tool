"""Pure Mac logic that runs on any OS: user data paths, Quartz coordinate flips, the Carbon key
table, pasteboard format mapping, the LaunchAgent plist. The real Quartz / Carbon / NSPasteboard
calls are covered by tests/test_mac_real.py (mac marker) on a Mac."""
from pathlib import Path

import pytest


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setenv("CAPTURE_PLATFORM", "darwin")


def test_MAC_01_user_data_lives_under_library_application_support(mac, monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from capture_tool.app import main
    from capture_tool.core import model_store as ms
    assert main.data_dir() == tmp_path / "Library" / "Application Support" / "CaptureTool"
    assert main.log_dir() == tmp_path / "Library" / "Logs" / "CaptureTool"
    assert ms.user_root() == tmp_path / "Library" / "Application Support" / "CaptureTool" / "models"
    assert main.fallback_dir() == tmp_path / "Pictures" / "Captures"
    monkeypatch.setenv("CAPTURE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert main.data_dir() == tmp_path / "Roaming" / "CaptureTool"                 # Windows unchanged


def test_MAC_02_quartz_coordinates_flip_to_top_left_physical_pixels():
    from capture_tool.core.geometry import Rect
    from capture_tool.platform.mac.screen import flip_rect, to_physical
    # Quartz / AppKit: origin at the bottom-left of the main display (900 logical px tall); a 100x50 box
    # whose bottom edge is 100 px above the bottom lies 750 px from the top
    assert flip_rect((10, 100, 100, 50), main_height=900) == Rect(10, 750, 100, 50)
    assert flip_rect((0, 0, 1440, 900), main_height=900) == Rect(0, 0, 1440, 900)
    assert to_physical(Rect(10, 750, 100, 50), scale=2.0) == Rect(20, 1500, 200, 100)
    assert to_physical(Rect(3, 3, 3, 3), scale=1.0) == Rect(3, 3, 3, 3)


def test_MAC_03_carbon_keys_from_a_hotkey():
    from capture_tool.core.hotkey import parse
    from capture_tool.platform.mac.hotkey import UnsupportedKey, carbon_keys
    assert carbon_keys(parse("Cmd+Shift+2")) == (0x13, 0x0100 | 0x0200)          # kVK_ANSI_2, cmdKey | shiftKey
    assert carbon_keys(parse("Ctrl+Option+`")) == (0x32, 0x1000 | 0x0800)        # kVK_ANSI_Grave, controlKey | optionKey
    assert carbon_keys(parse("F5")) == (0x60, 0)
    assert carbon_keys(parse("Alt+A")) == (0x00, 0x0800)
    with pytest.raises(UnsupportedKey):
        carbon_keys(parse("Alt+PrintScreen"))                                     # no such key on a Mac keyboard


def test_MAC_04_pasteboard_items_keep_png_html_and_text_and_drop_windows_only_formats():
    from capture_tool.core.clipboard_payload import DIB, GVML, HTML, PNG, UNICODE, cf_html
    from capture_tool.platform.mac.clipboard import pasteboard_items
    items = pasteboard_items({PNG: b"\x89PNG", DIB: b"dib", GVML: b"g", HTML: cf_html("<b>x</b>"), UNICODE: "hi"})
    assert items["public.png"] == b"\x89PNG" and items["public.utf8-plain-text"] == "hi"
    assert items["public.html"] == "<b>x</b>"                                       # the CF_HTML wrapper taken off
    assert set(items) == {"public.png", "public.html", "public.utf8-plain-text"}
    assert pasteboard_items({HTML: "<p>raw</p>"})["public.html"] == "<p>raw</p>"
    assert pasteboard_items({UNICODE: "x".encode("utf-16-le") + b"\x00\x00"})["public.utf8-plain-text"] == "x"
    assert pasteboard_items({}) == {}


def test_MAC_05_launch_agent_plist(monkeypatch, tmp_path):
    from capture_tool.platform.mac import startup
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    text = startup.plist_text("/Applications/CaptureTool.app/Contents/MacOS/CaptureTool")
    assert startup.LABEL == "com.capturetool.app" and f"<string>{startup.LABEL}</string>" in text
    assert "<string>--tray</string>" in text and "<key>RunAtLoad</key>" in text and "<true/>" in text
    assert "/Applications/CaptureTool.app/Contents/MacOS/CaptureTool" in text
    assert not startup.is_enabled()
    startup.set_enabled(True, "/Applications/CaptureTool.app/Contents/MacOS/CaptureTool")
    assert startup.is_enabled() and startup.plist_path() == tmp_path / "Library" / "LaunchAgents" / "com.capturetool.app.plist"
    assert "<string>--tray</string>" in startup.plist_path().read_text(encoding="utf-8")
    startup.set_enabled(False, "/x")
    assert not startup.is_enabled() and not startup.plist_path().exists()
    startup.set_enabled(False, "/x")                                              # off twice: nothing to remove, no error
