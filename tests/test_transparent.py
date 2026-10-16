"""배경 지우기: the paper (or screen) background becomes transparent so only the ink - a signature,
a stamp, writing - is left; the ink is split into colour layers that can be kept or dropped."""
import cv2
import numpy as np
from capture_tool.core.clipboard_payload import PNG
from capture_tool.core.export import apply_layers, ink_layers, on_checkerboard, remove_background
from capture_tool.core.settings import Settings
from tests.test_app import drag, make  # noqa: F401 (fixture)


def _paper():
    """Off-white paper with a lighting gradient, a black signature stroke, a red ring stamp."""
    h, w = 120, 200
    img = np.zeros((h, w, 3), np.uint8)
    for x in range(w):                                      # 235 .. 255: uneven lighting
        img[:, x] = 235 + (20 * x) // w
    cv2.polylines(img, [np.array([[20, 80], [50, 40], [80, 85], [110, 45], [140, 80]])], False, (20, 20, 20), 3)
    cv2.circle(img, (160, 60), 25, (40, 40, 200), 3)
    return img


def _ink_mask():
    m = np.zeros((120, 200), np.uint8)
    cv2.polylines(m, [np.array([[20, 80], [50, 40], [80, 85], [110, 45], [140, 80]])], False, 255, 3)
    cv2.circle(m, (160, 60), 25, 255, 3)
    return m > 0


def test_TR_01_paper_goes_transparent_ink_stays():
    out = remove_background(_paper())
    assert out.shape == (120, 200, 4)
    ink = _ink_mask()
    paper = ~cv2.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    assert (out[:, :, 3][paper] == 0).mean() > 0.98             # the gradient is not "ink"
    assert (out[:, :, 3][ink] > 200).mean() > 0.9                # the strokes are solid
    assert np.array_equal(out[:, :, :3][ink], _paper()[ink])     # colours untouched


def test_TR_02_ink_splits_into_colour_layers_that_can_be_dropped():
    out = remove_background(_paper())
    layers = ink_layers(out)
    names = [l.name for l in layers]
    assert len(layers) == 2 and any("검정" in n for n in names) and any("빨강" in n for n in names), names
    assert abs(sum(l.share for l in layers) - 1.0) < 1e-6
    keep = [("빨강" not in l.name) for l in layers]
    only_black = apply_layers(out, layers, keep)
    red = (only_black[:, :, 2] > 150) & (only_black[:, :, 1] < 100)
    assert (only_black[:, :, 3][red] == 0).all()                 # the stamp is gone ...
    assert only_black[:, :, 3].max() == 255                      # ... the signature stays
    assert apply_layers(out, layers, [True, True]) is not out and np.array_equal(apply_layers(out, layers, [True, True]), out)


def test_TR_03_the_users_signature_and_stamp_photos():
    stamp = remove_background(cv2.imread("tests/data/signature_stamp.png"))
    assert (stamp[:, :, 3] == 0).mean() > 0.4                    # most of the paper is gone
    assert any("빨강" in l.name for l in ink_layers(stamp))       # the red stamp is its own layer
    lines = remove_background(cv2.imread("tests/data/signature_lines.png"))
    assert (lines[:, :, 3] == 0).mean() > 0.5 and (lines[:, :, 3] > 200).sum() > 100


def test_TR_04_level_and_dark_background():
    img = _paper()
    cv2.line(img, (0, 100), (200, 100), (205, 205, 205), 1)      # a faint ruling line (diff ~40)
    faint = remove_background(img, level=1)[:, :, 3][100, 10] > 0
    strong = remove_background(img, level=4)[:, :, 3][100, 10] == 0
    assert faint and strong                                       # level: what still counts as ink
    dark = np.full((60, 160, 3), 30, np.uint8)                    # a dark-mode screenshot ...
    cv2.putText(dark, "Hi", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (240, 240, 240), 3)
    out = remove_background(dark)
    assert out[:, :, 3][5, 5] == 0 and (out[:, :, 3] > 200).sum() > 100   # ... keeps its light text


def test_TR_05_a_lasso_cut_stays_cut_and_the_preview_is_opaque():
    img = np.dstack([_paper(), np.full((120, 200), 255, np.uint8)])
    img[:, :100, 3] = 0                                           # left half already cut away
    out = remove_background(img)
    assert out[:, :100, 3].max() == 0 and out[:, 100:, 3].max() == 255
    pv = on_checkerboard(out)
    assert pv.shape == (120, 200, 3) and pv[0, 0, 0] != pv[0, 12, 0]   # the squares show through


def test_TR_06_button_copies_a_transparent_png_and_saves_it(make, tmp_path):
    c = make(settings=Settings(save_dir=str(tmp_path / "shots"), auto_save=True, image_format="jpg"))
    c.ask_transparent = lambda img, settings: remove_background(img)
    c.start_capture()
    ov = c.overlays[0]
    assert "transparent" in ov.side_bar.buttons
    drag(ov, (100, 100), (500, 400))
    c.on_toolbar_action("transparent")
    png = cv2.imdecode(np.frombuffer(c.clipboard.last[PNG], np.uint8), cv2.IMREAD_UNCHANGED)
    assert png.shape == (300, 400, 4)
    assert "투명" in c.messages[-1]
    files = list((tmp_path / "shots").glob("*"))
    assert len(files) == 1 and files[0].suffix == ".png"          # never JPG: it has no transparency
    assert c.session.selection is None                            # the capture is finished


def test_TR_07_cancel_keeps_the_plain_capture(make):
    c = make()
    c.ask_transparent = lambda img, settings: None
    c.start_capture()
    drag(c.overlays[0], (100, 100), (500, 400))
    c.on_toolbar_action("transparent")
    assert "취소" in c.messages[-1]
    png = cv2.imdecode(np.frombuffer(c.clipboard.last[PNG], np.uint8), cv2.IMREAD_UNCHANGED)
    assert png.shape[:2] == (300, 400)


def test_TR_08_dialog_previews_layers_and_remembers_the_level(qt_app):
    from capture_tool.app.transparent_dialog import TransparentDialog
    s = Settings(transparent_level=3)
    d = TransparentDialog(_paper(), s)
    assert d.level() == 3
    assert len(d.layer_boxes) == 2 and all(b.isChecked() for b in d.layer_boxes)
    d.layer_boxes[[i for i, l in enumerate(d.layers) if "빨강" in l.name][0]].setChecked(False)
    out = d.result_image()
    assert out.shape[2] == 4 and (out[:, :, 3][(out[:, :, 2] > 150) & (out[:, :, 1] < 100)] == 0).all()
    d.slider.setValue(1)
    assert d.level() == 1 and len(d.layer_boxes) >= 1 and d.chosen()[0] == 1
