"""The still picture behind the capture screen (BUG-142): DXGI desktop duplication when it has the
picture, the old GDI grab otherwise - GPU-drawn windows (Windows Terminal running herdr) came out white."""
import numpy as np

from capture_tool.core.frames import still_frame
from capture_tool.core.geometry import Rect

R = Rect(0, 0, 200, 120)


def picture(seed=1):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (R.h, R.w, 4), dtype=np.uint8)


def flat(v=255):
    return np.full((R.h, R.w, 4), v, np.uint8)


def test_FRAME_01_the_dxgi_picture_is_used_when_it_has_one():
    dx, gdi = picture(1), flat(255)                       # GDI: the terminal came out white
    assert still_frame(R, lambda r: dx, lambda r: gdi) is dx


def test_FRAME_02_no_dxgi_means_the_old_grab():
    gdi = picture(2)

    def broken(r):
        raise OSError("DXGI_ERROR_UNSUPPORTED (remote desktop)")
    assert still_frame(R, broken, lambda r: gdi) is gdi
    assert still_frame(R, lambda r: None, lambda r: gdi) is gdi


def test_FRAME_03_a_blank_or_wrong_size_dxgi_picture_falls_back():
    gdi = picture(3)
    assert still_frame(R, lambda r: flat(0), lambda r: gdi) is gdi                 # black: e.g. a secure screen
    assert still_frame(R, lambda r: np.zeros((10, 10, 4), np.uint8), lambda r: gdi) is gdi
    both_flat = flat(0)
    assert still_frame(R, lambda r: both_flat, lambda r: flat(255)) is not None    # never fails
