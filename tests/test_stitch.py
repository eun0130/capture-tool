"""Scroll capture: joining overlapping screenshots into one tall image."""
import numpy as np
import pytest

from capture_tool.core.stitch import ADDED, FULL, NOMATCH, SAME, Stitcher
from tests.scrollsim import FakePage, make_page


def run(fp: FakePage, notches=-8, steps=200, **kw) -> Stitcher:
    st = Stitcher(**kw)
    st.add(fp.frame())
    for _ in range(steps):
        fp.wheel(notches)
        r = st.add(fp.frame())
        if r.status in (SAME, FULL, NOMATCH):
            break
    return st


def test_STI_01_plain_page_is_rebuilt_exactly():
    fp = FakePage(make_page(2000), vh=500, px_per_notch=40)
    out = run(fp).result()
    assert out.shape == fp.expected().shape
    assert np.array_equal(out, fp.expected())


def test_STI_02_sticky_header_and_footer_appear_once():
    fp = FakePage(make_page(2000), vh=500, header=50, footer=30)
    out = run(fp).result()
    assert np.array_equal(out, fp.expected())
    assert out.shape[0] == 50 + 2000 + 30


def test_STI_03_moving_scrollbar_is_cut_off():
    fp = FakePage(make_page(2000), vh=500, scrollbar=14)
    out = run(fp).result()
    assert 480 <= out.shape[1] <= 482               # the moving scrollbar thumb strip is removed
    assert np.array_equal(out[:, :480], fp.expected())


def test_STI_04_no_movement_is_reported_as_same():
    fp = FakePage(make_page(2000), stuck=True)
    st = Stitcher()
    assert st.add(fp.frame()).status == ADDED       # the first frame starts the picture
    fp.wheel(-3)
    r = st.add(fp.frame())
    assert r.status == SAME and r.shift == 0
    assert st.result().shape[0] == 500


def test_STI_05_end_of_page_partial_last_step():
    fp = FakePage(make_page(1234), vh=500, px_per_notch=37)
    out = run(fp, notches=-9).result()
    assert np.array_equal(out, fp.expected())       # last step moves less than a full step


def test_STI_06_jump_without_overlap_is_nomatch():
    page = make_page(3000)
    st = Stitcher()
    st.add(page[0:500].copy())
    r = st.add(page[900:1400].copy())
    assert r.status == NOMATCH
    assert st.result().shape[0] == 500              # keeps what was joined so far


def test_STI_07_height_cap_stops_and_keeps_limit():
    fp = FakePage(make_page(5000), vh=500)
    st = run(fp, max_height=1800)
    out = st.result()
    assert out.shape[0] == 1800
    assert np.array_equal(out, fp.expected()[:1800])
    assert st.truncated


def test_STI_08_pixel_budget_cap():
    fp = FakePage(make_page(5000, w=480), vh=500)
    st = run(fp, max_pixels=480 * 1000)
    assert st.result().shape[0] <= 1000 and st.truncated


def test_STI_09_small_animated_area_is_tolerated():
    fp = FakePage(make_page(2000), vh=500)
    st = Stitcher()
    st.add(fp.frame())
    for i in range(80):
        fp.wheel(-6)
        f = fp.frame()
        f[200:208, 300:340] = (i * 37 % 255, 0, 255)   # a blinking badge in the viewport
        r = st.add(f)
        if r.status != ADDED:
            break
    out = st.result()
    assert abs(out.shape[0] - 2000) <= 8


def test_STI_10_blank_stretch_in_the_middle():
    fp = FakePage(make_page(2600, blank_gap=(900, 1150)), vh=500, px_per_notch=40)
    out = run(fp, notches=-5).result()
    assert np.array_equal(out, fp.expected())


def test_STI_11_expected_shift_breaks_ties_in_repeating_content():
    tile = make_page(60, seed=5)
    page = np.vstack([make_page(300, seed=3)] + [tile] * 30 + [make_page(300, seed=4)])  # repeating rows
    fp = FakePage(page, vh=400, px_per_notch=40)
    st = Stitcher()
    st.add(fp.frame())
    fp.wheel(-5)
    st.add(fp.frame(), expected=200)
    while True:
        fp.wheel(-5)
        r = st.add(fp.frame(), expected=200)
        if r.status != ADDED:
            break
    assert np.array_equal(st.result(), fp.expected())


def test_STI_12_frame_size_change_is_rejected():
    st = Stitcher()
    st.add(np.zeros((100, 100, 3), np.uint8))
    with pytest.raises(ValueError):
        st.add(np.zeros((90, 100, 3), np.uint8))


def test_STI_13_bgra_and_speed():
    import time
    fp = FakePage(make_page(4000, w=1600), vh=1000, px_per_notch=100)
    st = Stitcher()
    st.add(np.dstack([fp.frame(), np.full((1000, 1600, 1), 255, np.uint8)]))
    t = time.perf_counter()
    fp.wheel(-5)
    r = st.add(np.dstack([fp.frame(), np.full((1000, 1600, 1), 255, np.uint8)]))
    assert r.status == ADDED and r.shift == 500
    assert time.perf_counter() - t < 0.5                # per step, 1600x1000 frame
    assert st.result().shape[2] == 3


def test_STI_14_popup_bar_over_part_of_the_width_still_matches():
    fp = FakePage(make_page(2400), vh=500, px_per_notch=40)
    st = Stitcher()
    st.add(fp.frame())
    k = 0
    while True:
        fp.wheel(-7)
        f = fp.frame()
        k += 1
        if k >= 3:                                  # a translucent bar pops up over the right 2/3
            f[60:90, 160:] = (f[60:90, 160:] // 2 + 60).astype(f.dtype)
        r = st.add(f)
        if r.status != ADDED:
            break
    assert r.status == SAME
    out = st.result()
    assert out.shape[0] == 2400
    ok = (out == fp.expected()).all(axis=(1, 2))
    assert ok.mean() > 0.97                         # only the rows under the bar can differ


def test_STI_15_small_rendering_differences_between_frames_still_join():
    """150% display + fractional scroll: text edges come out a few levels different each frame."""
    rng = np.random.default_rng(3)
    fp = FakePage(make_page(2400), vh=500, px_per_notch=40)

    def jitter(f):
        noise = rng.integers(-3, 4, f.shape)
        return np.clip(f.astype(int) + noise, 0, 255).astype(np.uint8)
    st = Stitcher()
    st.add(jitter(fp.frame()))
    while True:
        fp.wheel(-7)
        r = st.add(jitter(fp.frame()))
        if r.status != ADDED:
            break
    assert r.status == SAME                                 # the end is still recognized
    out = st.result()
    assert out.shape == fp.expected().shape
    assert np.abs(out.astype(int) - fp.expected()).mean() < 3


def test_STI_16_tolerant_match_is_fast_enough():
    import time
    rng = np.random.default_rng(4)
    fp = FakePage(make_page(4000, w=1300), vh=1000, px_per_notch=100)
    st = Stitcher()
    st.add(fp.frame())
    fp.wheel(-5)
    f = np.clip(fp.frame().astype(int) + rng.integers(-3, 4, (1000, 1300, 3)), 0, 255).astype(np.uint8)
    t = time.perf_counter()
    r = st.add(f)
    assert r.status == ADDED and r.shift == 500
    assert time.perf_counter() - t < 1.5
