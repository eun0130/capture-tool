"""Freeform (lasso) crop: keep only the inside of the drawn outline."""
import numpy as np

from capture_tool.core.clip import MIN_CLIP_AREA, clip_image, flatten, mask_outside, polygon

IMG = np.full((100, 200, 3), (10, 120, 250), np.uint8)
TRI = [(20, 10), (120, 10), (70, 90)]


def test_CLIP_01_result_is_cut_to_the_outline_bounding_box():
    out = clip_image(IMG, TRI)
    assert out.shape == (81, 101, 4)                    # x 20..120, y 10..90 inclusive


def test_CLIP_02_inside_kept_outside_transparent_white():
    out = clip_image(IMG, TRI)
    assert tuple(out[20, 50]) == (10, 120, 250, 255)     # inside the triangle
    assert tuple(out[78, 2]) == (255, 255, 255, 0)       # bottom-left corner: outside


def test_CLIP_03_fewer_than_three_points_or_tiny_area_is_no_clip():
    assert polygon([(0, 0), (50, 50)], 200, 100) is None
    assert polygon([(0, 0), (1, 0), (1, 1)], 200, 100) is None   # area < MIN_CLIP_AREA
    assert polygon([(0, 0), (100, 0), (200, 0)], 200, 100) is None  # all on one line
    assert clip_image(IMG, [(0, 0), (1, 1)]) is None
    assert MIN_CLIP_AREA >= 16


def test_CLIP_04_points_outside_the_image_are_clamped():
    out = clip_image(IMG, [(-50, -50), (500, -50), (500, 500), (-50, 500)])
    assert out.shape == (100, 200, 4) and (out[:, :, 3] == 255).all()


def test_CLIP_05_self_crossing_outline_still_works():
    bow = [(10, 10), (190, 90), (190, 10), (10, 90)]    # figure-eight
    out = clip_image(IMG, bow)
    assert out is not None and out[:, :, 3].any() and not out[:, :, 3].all()


def test_CLIP_06_flatten_puts_transparent_parts_on_white():
    out = flatten(clip_image(IMG, TRI))
    assert out.shape[2] == 3
    assert tuple(out[78, 2]) == (255, 255, 255) and tuple(out[20, 50]) == (10, 120, 250)
    same = flatten(IMG)
    assert same.shape == IMG.shape


def test_CLIP_07_mask_outside_keeps_size_for_recognition():
    m = mask_outside(IMG, TRI)
    assert m.shape == IMG.shape
    assert tuple(m[95, 5]) == (255, 255, 255) and tuple(m[20, 70]) == (10, 120, 250)
    assert mask_outside(IMG, None) is IMG


def test_CLIP_08_float_points_and_grayscale_ok():
    g = np.full((50, 50), 7, np.uint8)
    out = clip_image(g, [(5.5, 5.2), (40.7, 5.1), (20.3, 44.9)])
    assert out.shape[2] == 4 and out[:, :, 3].any()
