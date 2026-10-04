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


def test_NAME_LONG_01_full_path_stays_under_the_windows_limit(tmp_path):
    from capture_tool.core.naming import unique_path
    deep = tmp_path / ("하위폴더" * 8) / ("folder" * 6)
    deep.mkdir(parents=True)
    p = unique_path(deep, "회의록_" * 80, ".png")
    assert len(str(p)) <= 250 and p.suffix == ".png" and p.stem.startswith("회의록")
    p.write_bytes(b"x")                                     # really writable
    q = unique_path(deep, "회의록_" * 80, ".png")             # the next one gets _1, still short
    assert q != p and len(str(q)) <= 256


def test_NAME_10_default_starts_with_the_date():
    """User (v0.8.1): drop "Capture_", start with YYMMDD."""
    from capture_tool.core.settings import Settings
    assert render(Settings().filename_pattern, NOW) == "260926_143012"


def test_NAME_11_old_default_moves_to_the_new_one_custom_kept():
    from capture_tool.core import settings as S
    s, warn = S.Settings(), []
    S._apply(s, {"filename_pattern": "Capture_{date}_{time}"}, warn)
    assert s.filename_pattern == "{yymmdd}_{time}"
    S._apply(s, {"filename_pattern": "회의_{date}"}, warn)
    assert s.filename_pattern == "회의_{date}"
