import json
import os

import pytest

from capture_tool.core import settings as st
from capture_tool.core.settings import Settings, load, save


def test_SET_01_missing_file_gives_defaults(tmp_path):
    s, warnings = load(tmp_path / "settings.json")
    assert s == Settings()
    assert warnings == []
    assert s.hotkeys["capture"] == "Alt + ~"


def test_SET_02_round_trip(tmp_path):
    p = tmp_path / "settings.json"
    s = Settings(save_dir="D:\\캡처", image_format="jpg", jpg_quality=80, auto_save=True)
    s.hotkeys["ocr"] = "Ctrl + Shift + 2"
    save(s, p)
    loaded, warnings = load(p)
    assert loaded == s
    assert warnings == []


def test_SET_03_corrupt_json_backed_up(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json", encoding="utf-8")
    s, warnings = load(p)
    assert s == Settings()
    assert warnings
    assert (tmp_path / "settings.json.bak").read_text(encoding="utf-8") == "{not json"


def test_SET_04_wrong_type_only_that_field_reset(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"jpg_quality": "high", "auto_save": True}), encoding="utf-8")
    s, warnings = load(p)
    assert s.jpg_quality == Settings().jpg_quality
    assert s.auto_save is True
    assert any("jpg_quality" in w for w in warnings)


def test_SET_05_invalid_hotkey_reset(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hotkeys": {"capture": "Ctrl+Foo", "ocr": "Ctrl+Shift+2"}}), encoding="utf-8")
    s, warnings = load(p)
    assert s.hotkeys["capture"] == "Alt + ~"
    assert s.hotkeys["ocr"] == "Ctrl + Shift + 2"
    assert any("capture" in w for w in warnings)


def test_SET_12_old_default_hotkey_migrated(tmp_path):
    """v1 shipped Win+~ as default (taken by Windows Terminal); v2 default is Alt+~."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hotkeys": {"capture": "Win + ~"}}), encoding="utf-8")
    s, warnings = load(p)
    assert s.hotkeys["capture"] == "Alt + ~"
    assert any("Alt + ~" in w for w in warnings)


def test_SET_13_user_choice_after_v2_kept(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"version": 2, "hotkeys": {"capture": "Win + ~"}}), encoding="utf-8")
    s, warnings = load(p)
    assert s.hotkeys["capture"] == "Win + ~"
    assert warnings == []


def test_SET_14_last_save_dir_round_trip(tmp_path):
    p = tmp_path / "settings.json"
    save(Settings(last_save_dir="D:\\보고서"), p)
    assert load(p)[0].last_save_dir == "D:\\보고서"


def test_SET_05b_empty_hotkey_means_disabled(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hotkeys": {"fullscreen": ""}}), encoding="utf-8")
    s, warnings = load(p)
    assert s.hotkeys["fullscreen"] == ""
    assert warnings == []


def test_SET_06_unknown_keys_ignored(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"whatever": 1, "auto_save": True}), encoding="utf-8")
    s, warnings = load(p)
    assert s.auto_save is True
    assert warnings == []


@pytest.mark.parametrize("q,expected", [(0, 1), (150, 100), (55, 55)])
def test_SET_07_jpg_quality_clamped(tmp_path, q, expected):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"jpg_quality": q}), encoding="utf-8")
    s, _ = load(p)
    assert s.jpg_quality == expected


def test_SET_08_bad_format_falls_back_to_png(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"image_format": "bmp"}), encoding="utf-8")
    s, warnings = load(p)
    assert s.image_format == "png"
    assert warnings


def test_SET_09_recent_colors_sanitized(tmp_path):
    p = tmp_path / "settings.json"
    colors = ["#e03131", "#E03131", "red", "#FAB005", "#1", "#000", "#111111", "#222222",
              "#333333", "#444444", "#555555", "#666666", "#777777"]
    p.write_text(json.dumps({"recent_colors": colors}), encoding="utf-8")
    s, _ = load(p)
    assert s.recent_colors == ["#E03131", "#FAB005", "#000000", "#111111",
                               "#222222", "#333333", "#444444", "#555555"]


def test_SET_10_atomic_save_keeps_old_file_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    save(Settings(auto_save=True), p)
    before = p.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(st.os, "replace", boom)
    with pytest.raises(OSError):
        save(Settings(auto_save=False), p)
    assert p.read_text(encoding="utf-8") == before
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_SET_11_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "settings.json"
    save(Settings(), p)
    assert p.exists()
