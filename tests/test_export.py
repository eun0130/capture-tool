"""크기 줄이기 / PDF 저장 core: pure image maths and PDF bytes (no UI, no Windows)."""
import io

import cv2
import numpy as np
import pytest

from capture_tool.core.export import (A4_PORTRAIT_PX, estimate_bytes, image_to_pdf, resize_longest,
                                       resize_percent, resize_to_bytes)


def _img(w, h, c=(120, 180, 90)):
    a = np.empty((h, w, 3), np.uint8)
    a[:] = c
    cv2.rectangle(a, (w // 4, h // 4), (3 * w // 4, 3 * h // 4), (30, 30, 30), 3)
    return a


def test_EXP_01_longest_side_scales_both_keeping_ratio():
    out = resize_longest(_img(1920, 1080), 1280)
    assert out.shape[1] == 1280 and abs(out.shape[0] - 720) <= 1
    tall = resize_longest(_img(400, 2000), 1000)
    assert tall.shape[0] == 1000 and abs(tall.shape[1] - 200) <= 1


def test_EXP_02_never_upscales():
    img = _img(300, 200)
    assert resize_longest(img, 5000).shape == img.shape
    assert resize_percent(img, 400).shape == img.shape


def test_EXP_03_percent():
    out = resize_percent(_img(1000, 600), 50)
    assert out.shape[1] == 500 and out.shape[0] == 300
    assert resize_percent(_img(1000, 600), 100).shape == (600, 1000, 3)


def test_EXP_04_tiny_targets_stay_at_least_one_pixel():
    assert min(resize_percent(_img(10, 10), 1).shape[:2]) >= 1
    assert min(resize_longest(_img(10, 10), 1).shape[:2]) >= 1


def test_EXP_05_estimate_bytes_is_in_the_right_ballpark():
    img = _img(1280, 720)
    png = estimate_bytes(img, "png")
    jpg = estimate_bytes(img, "jpg")
    real_png = len(cv2.imencode(".png", img)[1])
    assert 0.3 * real_png <= png <= 3.0 * real_png


def test_EXP_06_resize_to_bytes_meets_the_budget():
    img = _img(1920, 1080)
    out, w, h = resize_to_bytes(img, 200_000, "jpg")
    assert len(cv2.imencode(".jpg", out)[1]) <= 220_000 and w <= 1920 and w >= 16


def test_EXP_07_resize_to_bytes_already_small_is_unchanged():
    img = _img(80, 60)
    out, w, h = resize_to_bytes(img, 5_000_000, "png")
    assert out.shape == img.shape


def test_EXP_08_pdf_single_page_is_a_valid_pdf():
    data = image_to_pdf(_img(800, 600), dpi=96)
    assert data[:5] == b"%PDF-" and b"%%EOF" in data[-1024:]
    assert len(data) > 1000


def test_EXP_09_long_capture_splits_into_several_a4_pages():
    tall = _img(900, A4_PORTRAIT_PX[1] * 3)                 # ~3 pages tall
    one = image_to_pdf(tall, dpi=96, fit_one_page=True)
    many = image_to_pdf(tall, dpi=96, fit_one_page=False)
    assert _page_count(many) >= 3 and _page_count(one) == 1


def _page_count(pdf: bytes) -> int:
    return pdf.count(b"/MediaBox")          # Pillow writes one MediaBox per page


def test_EXP_10_bgra_cutout_flattens_onto_white_for_pdf():
    bgra = np.zeros((100, 100, 4), np.uint8)
    bgra[:, :, 3] = 255
    bgra[25:75, 25:75] = (0, 0, 200, 255)
    data = image_to_pdf(bgra, dpi=96)
    assert data[:5] == b"%PDF-"
