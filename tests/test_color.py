import numpy as np
import pytest

from capture_tool.core.color import normalize_hex, pixel_color, push_recent, rgb_string


def test_COL_01_pixel_color():
    img = np.zeros((10, 10, 3), np.uint8)
    img[5, 7] = (64, 58, 52)  # BGR
    assert pixel_color(img, 7, 5) == "#343A40"
    assert rgb_string("#343A40") == "RGB 52,58,64"


def test_COL_02_out_of_bounds():
    img = np.zeros((10, 10, 3), np.uint8)
    assert pixel_color(img, 10, 0) is None
    assert pixel_color(img, -1, 0) is None


def test_COL_03_recent_colors():
    r = push_recent(["#111111", "#222222"], "#222222")
    assert r == ["#222222", "#111111"]
    r = push_recent([f"#00000{i}" for i in range(8)], "#ABCDEF")
    assert r[0] == "#ABCDEF" and len(r) == 8


@pytest.mark.parametrize("v,exp", [("#f00", "#FF0000"), ("#e03131", "#E03131"), ("E03131", "#E03131")])
def test_normalize_hex(v, exp):
    assert normalize_hex(v) == exp


@pytest.mark.parametrize("v", ["red", "#12", "#GGGGGG", "", None])
def test_normalize_hex_invalid(v):
    with pytest.raises(ValueError):
        normalize_hex(v)


def test_pixel_color_gray_and_bgra():
    g = np.full((2, 2), 128, np.uint8)
    assert pixel_color(g, 0, 0) == "#808080"
    bgra = np.zeros((2, 2, 4), np.uint8)
    bgra[0, 0] = (255, 0, 0, 255)
    assert pixel_color(bgra, 0, 0) == "#0000FF"
