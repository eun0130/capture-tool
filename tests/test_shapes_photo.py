"""도형PPT on slides with photos and big text (found by the 69-slide check of a recorded talk):
photos stay pictures, words never run off the slide, pieces of one line are joined, a white title on
a coloured bar keeps its colour."""
import io
import zipfile

import cv2
import numpy as np

from capture_tool.core.drawingml import DShape, gvml_package
from capture_tool.core.shapes import (Detected, _even_sizes, _fit_texts, _join_pieces, _with_photos,
                                      find_photos, text_style, to_drawing)


def _page(w=960, h=540):
    return np.full((h, w, 3), 255, np.uint8)


def _photo(h, w, seed=1):
    rng = np.random.default_rng(seed)
    base = cv2.resize(rng.integers(0, 255, (h // 8, w // 8, 3), dtype=np.uint8), (w, h), interpolation=cv2.INTER_CUBIC)
    return np.clip(base.astype(int) + rng.integers(-40, 40, (h, w, 3)), 0, 255).astype(np.uint8)


def test_PHOTO_01_a_photo_on_a_page_is_found_to_its_edge_and_text_alone_is_not():
    img = _page()
    img[100:400, 500:900] = _photo(300, 400)
    cv2.putText(img, "Agenda of the meeting", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (40, 40, 40), 2)
    rects = find_photos(img)
    assert len(rects) == 1
    x, y, w, h = rects[0]
    assert abs(x - 500) <= 8 and abs(y - 100) <= 8 and abs(w - 400) <= 16 and abs(h - 300) <= 16
    text_only = _page()
    for i in range(8):
        cv2.putText(text_only, f"Line {i}: the quick brown fox jumps", (30, 50 + 60 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 0), 2)
    assert find_photos(text_only) == []


def test_PHOTO_02_what_was_found_inside_a_photo_goes_and_the_photo_is_a_picture_at_the_back():
    img = _page()
    img[100:400, 500:900] = _photo(300, 400)
    det = [Detected("ellipse", 600, 200, 40, 40, fill="#AA3300"), Detected("text", 520, 120, 100, 30, text="40"),
           Detected("rect", 40, 40, 200, 80, fill="#3366CC", text="Agenda")]
    out = _with_photos(img, det)
    kinds = [d.kind for d in out]
    assert kinds[0] == "photo" and out[0].image[:2] == b"\xff\xd8"                  # a JPEG
    assert "ellipse" not in kinds and all(d.text != "40" for d in out) and any(d.text == "Agenda" for d in out)
    page = Detected("rect", 0, 0, 960, 540, fill="#FFFFFF")                          # a panel the photo sits on
    shapes, _ = to_drawing([page] + out)
    order = [s.image is not None for s in shapes]
    assert order.index(True) == 1                                                    # over the panel, under the rest


def test_PHOTO_03_a_background_photo_keeps_the_page_words_as_text_boxes_painted_out_of_it():
    img = _photo(540, 960, seed=3)
    cv2.rectangle(img, (100, 200), (860, 300), (250, 250, 250), -1)
    cv2.putText(img, "Founded two decades ago", (120, 265), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    lines = [("Founded two decades ago", (118, 228, 560, 48), 0.99)]
    out = _with_photos(img, [Detected("rect", 100, 200, 760, 100, fill="#FAFAFA")], lines)
    assert out[0].kind == "photo" and out[0].w * out[0].h > 0.8 * 960 * 540
    words = [d for d in out if d.kind == "text"]
    assert [d.text for d in words] == ["Founded two decades ago"] and words[0].fill is None
    pic = cv2.imdecode(np.frombuffer(out[0].image, np.uint8), cv2.IMREAD_COLOR)
    x0, y0 = out[0].x, out[0].y
    patch = pic[228 - y0:276 - y0, 130 - x0:600 - x0]
    assert (patch < 60).mean() < 0.02                                                 # the black letters are gone


def test_PHOTO_04_text_never_runs_off_its_box():
    d = Detected("text", 0, 0, 600, 40, text="PUBLIC LAW 104-113 NATIONAL TECHNOLOGY TRANSFER AND ADVANCEMENT ACT",
                 font_size=54)
    _fit_texts([d], 96)
    width_pt = sum(0.66 if c.isupper() else 0.5 for c in d.text) * d.font_size
    assert d.font_size <= 14 and width_pt <= 1.2 * 600 * 72 / 96
    ok = Detected("text", 0, 0, 600, 40, text="Legislation", font_size=28)
    _fit_texts([ok], 96)
    assert ok.font_size == 28


def test_PHOTO_05_overlapping_pieces_of_one_line_are_joined():
    a = Detected("text", 100, 100, 300, 30, text="two decades ago in resp", font_size=16)
    b = Detected("text", 360, 102, 320, 30, text="response to increasing demands", font_size=16)
    c = Detected("text", 100, 200, 300, 30, text="on process and product quality", font_size=16)
    out = _join_pieces([a, b, c])
    assert [d.text for d in out] == ["two decades ago in response to increasing demands", "on process and product quality"]
    assert out[0].w == 680 - 100


def test_PHOTO_06_lines_of_one_height_get_one_size():
    from capture_tool.core.shapes import TextStyle
    items = [("The Act gives the agencies", (0, 0, 500, 30), TextStyle("#000000", 16, False)),
             ("consensus standards where", (0, 32, 480, 31), TextStyle("#000000", 14, False)),
             ("or otherwise impractical.", (0, 64, 300, 30), TextStyle("#000000", 16, False)),
             ("Legislation", (0, 100, 300, 60), TextStyle("#FFFFFF", 32, True))]
    sizes = [st.size for _, _, st in _even_sizes(items)]
    assert sizes == [16, 16, 16, 32]


def test_PHOTO_07_a_white_title_on_a_blue_bar_stays_white_in_a_tight_box():
    img = np.full((140, 600, 3), (226, 171, 13), np.uint8)                 # the SAE blue (BGR)
    cv2.putText(img, "Legislation", (20, 95), cv2.FONT_HERSHEY_DUPLEX, 2.2, (253, 253, 253), 5)
    st = text_style(img, (22, 52, 395, 48), "Legislation")                  # tight on the letters
    assert st.color.upper() in ("#FDFDFD", "#FEFEFE", "#FFFFFF", "#FCFCFC") and st.size >= 24


def test_PHOTO_08_photos_travel_as_jpeg_in_the_clipboard_package():
    ok, jpg = cv2.imencode(".jpg", _photo(40, 60))
    pkg = gvml_package([DShape("rect", 0, 0, 60, 40, fill=None, stroke=None, image=jpg.tobytes()),
                        DShape("rect", 70, 0, 50, 30, text="x")], [])
    z = zipfile.ZipFile(io.BytesIO(pkg))
    assert "clipboard/media/image1.jpeg" in z.namelist()
    assert 'Extension="jpeg"' in z.read("[Content_Types].xml").decode()


def test_PHOTO_09_pieces_of_one_line_become_one_line_and_rows_stay_apart():
    from capture_tool.core.shapes import _join_row
    lines = [("Structured Certification:", (100, 100, 300, 30)), ("Clear roles, defined paths", (430, 102, 320, 28)),
             ("High-Quality Assurance:", (100, 150, 280, 30)), ("far away", (1400, 150, 100, 30))]
    out = sorted(_join_row(lines), key=lambda l: (l[1][1], l[1][0]))
    assert [t for t, _ in out] == ["Structured Certification: Clear roles, defined paths", "High-Quality Assurance:",
                                   "far away"]
    assert out[0][1][2] == 750 - 100
