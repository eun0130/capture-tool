from datetime import datetime
from pathlib import Path

import pytest

from capture_tool.core.naming import (
    SaveDirError,
    normalize_ext,
    render,
    resolve_save_dir,
    sanitize,
    unique_path,
)

NOW = datetime(2026, 9, 26, 14, 30, 12)


def test_NAME_01_render_pattern():
    assert render("Capture_{date}_{time}", NOW) == "Capture_20260926_143012"
    assert render("{datetime}", NOW) == "20260926_143012"


def test_NAME_02_unknown_token_kept():
    assert render("A_{foo}_{date}", NOW) == "A_{foo}_20260926"


def test_NAME_03_forbidden_chars_replaced():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize("tab\there\x01") == "tab_here_"


@pytest.mark.parametrize("name,expected", [("CON", "_CON"), ("nul.txt", "_nul.txt"), ("com1", "_com1"), ("Console", "Console")])
def test_NAME_04_reserved_names(name, expected):
    assert sanitize(name) == expected


def test_NAME_05_trailing_dots_spaces_and_empty():
    assert sanitize("report. . ") == "report"
    assert sanitize("") == "Capture"
    assert sanitize(" ... ") == "Capture"


def test_NAME_06_length_capped():
    assert len(sanitize("가" * 300)) == 200


def test_NAME_07_unique_suffix(tmp_path):
    (tmp_path / "Capture.png").write_bytes(b"x")
    (tmp_path / "Capture_1.png").write_bytes(b"x")
    assert unique_path(tmp_path, "Capture", "png") == tmp_path / "Capture_2.png"
    assert unique_path(tmp_path, "New", "png") == tmp_path / "New.png"


@pytest.mark.parametrize("ext,expected", [("PNG", ".png"), (".jpg", ".jpg"), ("jpeg", ".jpg"), ("JPG", ".jpg")])
def test_NAME_08_ext_normalized(ext, expected):
    assert normalize_ext(ext) == expected


def test_NAME_08b_unsupported_ext():
    with pytest.raises(ValueError):
        normalize_ext("exe")


def test_NAME_09_fallback_when_unwritable(tmp_path):
    good = tmp_path / "fallback"
    d, used = resolve_save_dir(Path("Z:/nope"), good, is_writable=lambda p: p == good)
    assert (d, used) == (good, True)
    d, used = resolve_save_dir("", good, is_writable=lambda p: True)
    assert (d, used) == (good, True)
    d, used = resolve_save_dir(tmp_path, good, is_writable=lambda p: True)
    assert (d, used) == (tmp_path, False)


def test_NAME_10_both_unwritable():
    with pytest.raises(SaveDirError):
        resolve_save_dir("Z:/a", "Z:/b", is_writable=lambda p: False)


def test_NAME_11_korean_kept(tmp_path):
    assert sanitize("회의_메모") == "회의_메모"
    assert unique_path(tmp_path, "회의", ".png").name == "회의.png"


def test_default_is_writable_creates_dir(tmp_path):
    target = tmp_path / "new" / "dir"
    d, used = resolve_save_dir(target, tmp_path)
    assert d == target and used is False and target.is_dir()
