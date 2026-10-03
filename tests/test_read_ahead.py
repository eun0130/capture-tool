"""Read ahead: right after an area is chosen the text is read in the background, so 텍스트 / 표 /
도형PPT / 글자로 검색 answer at once instead of reading again (0.4-0.7 s on a screen form)."""
import threading

from capture_tool.core.ocr import OcrLine, OcrUnavailable
from tests.test_app import drag, make  # noqa: F401 (fixture)
from capture_tool.core.clipboard_payload import UNICODE


class CountingOcr:
    def __init__(self, lines=(), fail=False, gate=None):
        self.lines, self.fail, self.gate = list(lines), fail, gate
        self.calls = 0
        self.ready = True

    def recognize(self, img):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise OcrUnavailable("엔진 없음")
        return list(self.lines)

    def warmup(self):
        pass


LINES = [OcrLine("견적 요약", (10, 10, 100, 20), 0.99)]


def _select(c, a=(100, 100), b=(400, 300)):
    c.start_capture()
    drag(c.overlays[0], a, b)
    return c.overlays[0]


def test_AHEAD_01_text_uses_what_was_read_ahead(make):
    ocr = CountingOcr(LINES)
    c = make(ocr=ocr)
    c.read_ahead_mode = "inline"
    ov = _select(c)
    assert ocr.calls == 1                                    # read as soon as the area was chosen
    ov.toolbar.trigger("text")
    assert ocr.calls == 1 and "견적 요약" in c.clipboard.last[UNICODE]


def test_AHEAD_02_a_new_area_is_read_again(make):
    ocr = CountingOcr(LINES)
    c = make(ocr=ocr)
    c.read_ahead_mode = "inline"
    _select(c)
    c.cancel()
    _select(c, (50, 60), (300, 260))
    assert ocr.calls == 2
    c.on_toolbar_action("text")
    assert ocr.calls == 2


def test_AHEAD_03_off_in_settings(make):
    ocr = CountingOcr(LINES)
    c = make(ocr=ocr)
    c.read_ahead_mode = "inline"
    c.settings.read_ahead = False
    ov = _select(c)
    assert ocr.calls == 0
    ov.toolbar.trigger("text")
    assert ocr.calls == 1


def test_AHEAD_04_engine_missing_is_reported_once_used(make):
    ocr = CountingOcr(fail=True)
    c = make(ocr=ocr)
    c.read_ahead_mode = "inline"
    _select(c)                                               # no message just for choosing an area
    assert not [m for m in c.messages if "엔진" in m]
    c.on_toolbar_action("text")
    assert ocr.calls == 1                                    # the failure is reused, not retried


def test_AHEAD_05_waits_for_a_read_still_running(make):
    gate = threading.Event()
    ocr = CountingOcr(LINES, gate=gate)
    c = make(ocr=ocr)
    c.read_ahead_mode = "thread"
    c.start_capture()
    drag(c.overlays[0], (100, 100), (400, 300))              # background read is blocked on the gate
    threading.Timer(0.2, gate.set).start()
    c.on_toolbar_action("text")                              # sync controller: waits for that read
    assert ocr.calls == 1 and "견적 요약" in c.clipboard.last[UNICODE]


def test_AHEAD_06_huge_area_is_not_read_ahead(make):
    from capture_tool.app import controller as C
    ocr = CountingOcr(LINES)
    c = make(ocr=ocr)
    c.read_ahead_mode = "inline"
    old = C.READ_AHEAD_MAX_PX
    C.READ_AHEAD_MAX_PX = 1000
    try:
        _select(c)
    finally:
        C.READ_AHEAD_MAX_PX = old
    assert ocr.calls == 0
