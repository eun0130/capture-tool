"""Scroll capture driver: wheel, wait, grab, join — until the end, a stop, or a limit."""
import numpy as np

from capture_tool.core.scroll_session import ScrollCapture
from tests.scrollsim import FakePage, make_page


def drive(sc: ScrollCapture) -> list[int]:
    """Run the generator synchronously; returns the waits it asked for (ms)."""
    return list(sc.run())


def cap(fp, **kw) -> ScrollCapture:
    return ScrollCapture(grab=fp.frame, wheel=fp.wheel, **kw)


def test_SCR_01_from_current_position_to_the_end():
    fp = FakePage(make_page(2000), vh=500, px_per_notch=40, start=300)
    sc = cap(fp)
    drive(sc)
    assert sc.reason == "end"
    assert np.array_equal(sc.result(), fp.expected(top=300))


def test_SCR_02_full_page_scrolls_to_the_top_first():
    fp = FakePage(make_page(2000), vh=500, header=40, start=900)
    sc = cap(fp, to_top=True)
    drive(sc)
    assert sc.reason == "end" and any(n > 0 for n in fp.wheels)     # wheeled up first
    assert np.array_equal(sc.result(), fp.expected())


def test_SCR_03_step_size_adapts_to_the_view_height():
    fp = FakePage(make_page(6000), vh=600, px_per_notch=20)
    sc = cap(fp)
    drive(sc)
    downs = [n for n in fp.wheels if n < 0]
    assert downs[0] == -1 and min(downs[2:]) <= -10        # careful first step, then bigger ones
    assert np.array_equal(sc.result(), fp.expected())
    assert len(downs) < 30                                 # not hundreds of tiny steps


def test_SCR_04_steps_keep_enough_overlap():
    fp = FakePage(make_page(4000), vh=300, px_per_notch=120)   # one notch is 40% of the view
    sc = cap(fp)
    drive(sc)
    assert all(n == -1 for n in fp.wheels if n < 0)
    assert np.array_equal(sc.result(), fp.expected())


def test_SCR_05_window_that_does_not_scroll():
    fp = FakePage(make_page(2000), stuck=True)
    sc = cap(fp)
    drive(sc)
    assert sc.reason == "noscroll" and sc.result().shape[0] == 500


def test_SCR_06_stop_request_keeps_what_was_captured():
    fp = FakePage(make_page(5000), vh=500)
    n = {"k": 0}

    def stop():
        n["k"] += 1
        return n["k"] > 4
    sc = cap(fp, stop_requested=stop)
    drive(sc)
    assert sc.reason == "stopped"
    out = sc.result()
    assert 500 < out.shape[0] < 5000 and np.array_equal(out, fp.expected()[:out.shape[0]])


def test_SCR_07_lazy_loading_page_gets_a_second_chance():
    fp = FakePage(make_page(1500), vh=500, grows_to=2500)
    sc = cap(fp)
    drive(sc)
    assert sc.reason == "end" and sc.result().shape[0] == 2500


def test_SCR_08_step_limit():
    fp = FakePage(make_page(20000), vh=500, px_per_notch=10)
    sc = cap(fp, max_steps=5)
    drive(sc)
    assert sc.reason == "limit" and sc.steps == 5


def test_SCR_09_height_limit_reported():
    fp = FakePage(make_page(8000), vh=500)
    sc = cap(fp, max_height=2000)
    drive(sc)
    assert sc.reason == "full" and sc.result().shape[0] == 2000


def test_SCR_10_waits_are_short_and_bounded():
    fp = FakePage(make_page(2000), vh=500)
    sc = cap(fp)
    waits = drive(sc)
    assert all(0 < w <= 500 for w in waits)


def test_SCR_11_settles_until_two_grabs_match():
    fp = FakePage(make_page(2000), vh=500)
    frames = {"n": 0}

    def smooth_grab():                       # smooth scrolling: first grab after a wheel is mid-way
        frames["n"] += 1
        f = fp.frame()
        if frames["n"] % 3 == 1:
            f = f.copy()
            f[:, :] = f[:, :] // 2
        return f
    sc = ScrollCapture(grab=smooth_grab, wheel=fp.wheel)
    drive(sc)
    assert np.array_equal(sc.result(), fp.expected())


def test_SCR_12_scroll_to_top_gives_up_after_limit():
    fp = FakePage(make_page(2000), vh=500, start=1000)
    fp.wheel = lambda n, _w=fp.wheel: _w(n) if n < 0 else None   # can't scroll up
    sc = cap(fp, to_top=True)
    drive(sc)
    assert sc.reason == "end" and np.array_equal(sc.result(), fp.expected(top=1000))


def test_SCR_13_progress_callback():
    fp = FakePage(make_page(2000), vh=500)
    seen = []
    sc = cap(fp, progress=lambda steps, height: seen.append((steps, height)))
    drive(sc)
    assert seen and seen[-1][1] == sc.result().shape[0]
    assert [s for s, _ in seen] == sorted(s for s, _ in seen)


def test_SCR_14_another_window_covering_the_area_stops_it():
    fp = FakePage(make_page(5000), vh=500)
    n = {"k": 0}

    def visible():
        n["k"] += 1
        return n["k"] < 4
    sc = cap(fp, still_visible=visible)
    drive(sc)
    assert sc.reason == "covered"
    out = sc.result()
    assert np.array_equal(out, fp.expected()[:out.shape[0]])


def test_SCR_15_one_unsettled_frame_is_retried_before_giving_up():
    fp = FakePage(make_page(2000), vh=500)
    state = {"bad": 0}

    def grab():
        f = fp.frame()
        if fp.offset > 800 and state["bad"] < 3:        # the view pauses mid-way for a moment
            state["bad"] += 1
            f = np.roll(f, 137, axis=0)
        return f
    sc = ScrollCapture(grab=grab, wheel=fp.wheel)
    drive(sc)
    assert sc.reason == "end"
    assert np.array_equal(sc.result(), fp.expected())


def test_SCR_16_capture_blanked_mid_way_waits_then_continues():
    fp = FakePage(make_page(2000), vh=500)
    state = {"blank": 0}

    def grab():
        f = fp.frame()
        if fp.offset > 600 and state["blank"] < 6:      # the screen grab comes back pure white a while
            state["blank"] += 1
            return np.full_like(f, 255)
        return f
    sc = ScrollCapture(grab=grab, wheel=fp.wheel)
    drive(sc)
    assert sc.reason == "end" and np.array_equal(sc.result(), fp.expected())


def test_SCR_17_capture_blocked_for_good_stops_with_blocked():
    fp = FakePage(make_page(3000), vh=500)

    def grab():
        f = fp.frame()
        return np.full_like(f, 255) if fp.offset > 600 else f
    sc = ScrollCapture(grab=grab, wheel=fp.wheel)
    drive(sc)
    assert sc.reason == "blocked"
    out = sc.result()
    assert out.shape[0] >= 500 and (out < 250).any()      # the blank frames are not glued on


def test_SCR_18_blocked_from_the_start():
    fp = FakePage(make_page(3000), vh=500)
    sc = ScrollCapture(grab=lambda: np.full((500, 480, 3), 255, np.uint8), wheel=fp.wheel)
    drive(sc)
    assert sc.reason == "blocked" and fp.wheels == []


def test_SCR_19_looks_blocked():
    from capture_tool.core.scroll_session import looks_blocked
    assert looks_blocked(np.full((300, 300, 3), 255, np.uint8))
    assert looks_blocked(np.zeros((300, 300, 4), np.uint8))
    img = np.full((300, 300, 3), 255, np.uint8)
    img[150, 150] = 0
    assert not looks_blocked(img)
    assert not looks_blocked(np.full((20, 20, 3), 255, np.uint8))     # tiny areas can be plain
