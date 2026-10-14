"""테두리 · 음영 — pure image maths in core/export.add_border (no UI)."""
import cv2
import numpy as np
import pytest

from capture_tool.core.export import add_border


def _img(h=40, w=60, v=200):
    return np.full((h, w, 3), v, np.uint8)


def test_BORD_01_no_border_no_shadow_returns_same_pixels():
    img = _img()
    out = add_border(img, thickness=0, shadow=False)
    assert out.shape == img.shape
    assert np.array_equal(out, img)


def test_BORD_02_thickness_grows_the_image_on_every_side():
    img = _img(40, 60)
    out = add_border(img, thickness=5, color=(0, 0, 0))
    assert out.shape[:2] == (50, 70)          # +2*5 each axis


def test_BORD_03_border_pixels_are_the_chosen_colour_bgr():
    img = _img()
    out = add_border(img, thickness=4, color=(0, 0, 255))   # red in BGR
    assert tuple(int(c) for c in out[0, 0]) == (0, 0, 255)   # a corner is border
    assert tuple(int(c) for c in out[2, 2]) == (0, 0, 255)
    assert tuple(int(c) for c in out[20, 30]) == (200, 200, 200)  # centre is the picture


def test_BORD_04_hex_colour_string_is_accepted():
    img = _img()
    out = add_border(img, thickness=3, color="#FFFFFF")
    assert tuple(int(c) for c in out[0, 0]) == (255, 255, 255)


def test_BORD_05_shadow_enlarges_the_canvas_and_keeps_the_picture_intact():
    img = _img(40, 60)
    out = add_border(img, thickness=0, shadow=True)
    assert out.shape[0] > 40 and out.shape[1] > 60      # margin added for the shadow
    # the original picture still sits inside, unchanged somewhere
    assert np.any(np.all(out == 200, axis=2))


def test_BORD_06_shadow_puts_dark_pixels_below_right_of_the_picture():
    img = _img(40, 60, v=255)                 # white picture on white bg: only the shadow is dark
    out = add_border(img, thickness=0, shadow=True,
                     shadow_offset=(10, 10), shadow_blur=10, shadow_opacity=0.6)
    gray = out.min(axis=2)
    assert gray.min() < 200                   # a visibly darker shadow region exists


def test_BORD_07_border_and_shadow_together():
    img = _img(40, 60)
    out = add_border(img, thickness=6, color=(10, 10, 10), shadow=True)
    assert out.shape[0] > 40 + 12 and out.shape[1] > 60 + 12


def test_BORD_08_grayscale_and_bgra_inputs_do_not_crash():
    g = np.full((30, 30), 128, np.uint8)
    assert add_border(g, thickness=3, color=(0, 0, 0)).shape[2] == 3
    bgra = np.dstack([_img(30, 30), np.full((30, 30), 128, np.uint8)])
    out = add_border(bgra, thickness=3, color=(0, 0, 0), shadow=True)
    assert out.ndim == 3 and out.shape[2] == 3


def test_BORD_09_negative_offset_shadow_is_still_valid():
    img = _img(40, 60, v=255)
    out = add_border(img, thickness=2, color=(0, 0, 0), shadow=True,
                     shadow_offset=(-8, -8), shadow_blur=8)
    assert out.ndim == 3 and out.dtype == np.uint8


def test_BORD_10_encodes_as_png_without_error():
    out = add_border(_img(), thickness=5, color=(50, 100, 150), shadow=True)
    ok, _ = cv2.imencode(".png", out)
    assert ok
