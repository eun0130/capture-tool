from capture_tool.core.geometry import Rect
from capture_tool.core.session import Action, CaptureSession, State

VB = Rect(0, 0, 1920, 1080)


def started():
    s = CaptureSession()
    assert s.hotkey(VB) is True
    return s


def test_SES_01_full_flow():
    s = started()
    assert s.state is State.SELECTING
    s.drag((100, 100), (400, 300))
    assert s.state is State.EDITING
    assert s.selection == Rect(100, 100, 300, 200)


def test_SES_02_hotkey_while_active_ignored():
    s = started()
    assert s.hotkey(VB) is False
    s.drag((100, 100), (400, 300))
    assert s.hotkey(VB) is False
    assert s.state is State.EDITING


def test_SES_03_escape_returns_to_idle():
    s = started()
    assert s.key("Escape") is Action.CANCEL
    assert s.state is State.IDLE
    s = started()
    s.drag((100, 100), (400, 300))
    assert s.key("Escape") is Action.CANCEL
    assert s.state is State.IDLE and s.selection is None


def test_SES_04_enter_without_selection_ignored():
    s = started()
    assert s.key("Enter") is Action.NONE
    assert s.state is State.SELECTING


def test_SES_05_finish_actions():
    for key, ctrl, shift, action in [
        ("Enter", False, False, Action.COPY),
        ("C", True, False, Action.COPY),
        ("S", True, False, Action.SAVE),
        ("S", True, True, Action.SAVE_AS),
        ("F3", False, False, Action.PIN),
    ]:
        s = started()
        s.drag((100, 100), (400, 300))
        assert s.key(key, ctrl=ctrl, shift=shift) is action
        assert s.state is State.IDLE
        assert s.result == Rect(100, 100, 300, 200)


def test_SES_06_click_only_stays_selecting():
    s = started()
    s.drag((100, 100), (101, 101))
    assert s.state is State.SELECTING


def test_SES_07_reselect_keeps_annotations_relative():
    s = started()
    s.drag((100, 100), (400, 300))
    s.document.add_step((10, 10), "#E03131")
    s.resize(Rect(50, 80, 400, 300))
    assert s.selection == Rect(50, 80, 400, 300)
    # annotation stays at the same screen position: shifted by +50,+20 inside new region
    assert s.document.shapes[0].points == [(60, 30)]
    assert (s.document.width, s.document.height) == (400, 300)


def test_after_finish_new_capture_allowed():
    s = started()
    s.drag((100, 100), (400, 300))
    s.key("Enter")
    assert s.hotkey(VB) is True
    assert s.document is None or s.document.shapes == []
