import re
import struct

import numpy as np
import pytest

from capture_tool.core.clipboard_payload import (
    GVML,
    HTML,
    PNG,
    SVG,
    UNICODE,
    DIB,
    cf_html,
    dib_from_bgr,
    image_payload,
    png_with_dpi,
    shapes_payload,
    text_payload,
)


def offsets(data: bytes):
    head = data[:200].decode("ascii", "ignore")
    return {k: int(v) for k, v in re.findall(r"(StartHTML|EndHTML|StartFragment|EndFragment):(\d+)", head)}


def test_CLIP_01_cf_html_offsets():
    data = cf_html("<b>hi</b>")
    o = offsets(data)
    assert data[o["StartFragment"]:o["EndFragment"]] == b"<b>hi</b>"
    assert data[o["StartHTML"]:].startswith(b"<html>")
    assert o["EndHTML"] == len(data)


def test_CLIP_02_cf_html_korean_byte_offsets():
    frag = "<p>한글 텍스트</p>"
    data = cf_html(frag)
    o = offsets(data)
    assert data[o["StartFragment"]:o["EndFragment"]].decode("utf-8") == frag


def test_CLIP_03_text_payload_formats():
    p = text_payload("hello")
    assert p[UNICODE] == "hello"
    assert b"hello" in p[HTML]


def test_CLIP_04_newlines_crlf():
    p = text_payload("a\nb\r\nc\rd")
    assert p[UNICODE] == "a\r\nb\r\nc\r\nd"


def test_CLIP_05_table_payload():
    p = text_payload("ignored", table=[["품목", "수량"], ["A", "3"]])
    assert p[UNICODE] == "품목\t수량\r\nA\t3"
    html = p[HTML].decode("utf-8")
    assert "<table>" in html and html.count("<tr>") == 2 and "<td>품목</td>" in html


def test_CLIP_06_html_escaped():
    p = text_payload('<script>alert("x")</script> & co')
    html = p[HTML].decode("utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "&amp; co" in html


def test_CLIP_07_image_payload():
    p = image_payload(b"\x89PNG....", b"DIBDATA")
    assert list(p) == [PNG, DIB]


@pytest.mark.parametrize("args", [(b"", b"x"), (b"x", b"")])
def test_CLIP_08_empty_image(args):
    with pytest.raises(ValueError):
        image_payload(*args)


def test_CLIP_08b_empty_text():
    with pytest.raises(ValueError):
        text_payload("   ")


def test_CLIP_09_shapes_payload_order():
    p = shapes_payload(b"GV", "<svg/>", b"PNG")
    assert list(p) == [GVML, SVG, PNG]
    assert p[SVG] == b"<svg/>"


def test_dib_from_bgr_header_and_bottom_up():
    img = np.zeros((2, 3, 3), np.uint8)
    img[0, 0] = (1, 2, 3)  # top-left
    img[1, 0] = (4, 5, 6)  # bottom-left
    dib = dib_from_bgr(img)
    size, w, h, planes, bits, comp = struct.unpack("<IiiHHI", dib[:20])
    assert (size, w, h, planes, bits, comp) == (40, 3, 2, 1, 32, 0)
    pixels = dib[40:]
    assert len(pixels) == 3 * 2 * 4
    assert pixels[0:4] == bytes([4, 5, 6, 255])       # first stored row = bottom
    assert pixels[12:16] == bytes([1, 2, 3, 255])


def test_CLIP_10_png_carries_dpi():
    import cv2
    ok, png = cv2.imencode(".png", np.zeros((10, 20, 3), np.uint8))
    out = png_with_dpi(png.tobytes(), 144)
    i = out.index(b"pHYs")
    ppx, ppy, unit = struct.unpack(">IIB", out[i + 4:i + 13])
    assert (ppx, ppy, unit) == (5669, 5669, 1)       # 144 dpi in pixels per metre
    assert cv2.imdecode(np.frombuffer(out, np.uint8), 1).shape == (10, 20, 3)
    assert png_with_dpi(out, 96).count(b"pHYs") == 1  # replaces, never duplicates


def test_CLIP_11_dib_carries_dpi():
    dib = dib_from_bgr(np.zeros((2, 2, 3), np.uint8), dpi=144)
    xppm, yppm = struct.unpack("<ii", dib[24:32])
    assert (xppm, yppm) == (5669, 5669)


def test_dib_from_bgra_and_gray():
    assert len(dib_from_bgr(np.zeros((2, 2, 4), np.uint8))) == 40 + 16
    assert len(dib_from_bgr(np.zeros((2, 2), np.uint8))) == 40 + 16


def test_CLIP_12_table_cells_that_excel_would_change_stay_text():
    """Real Excel paste turned "007" into 7 and ran "=SUM(A1)" as a formula: text read off a
    screen must never become a formula, and codes keep their leading zeros."""
    from capture_tool.core.clipboard_payload import text_payload
    grid = [["코드", "수식", "음수", "날짜", "금액", "비율"],
            ["007", "=SUM(A1)", "-12", "2026-10-03", "1,250,000", "12.5%"],
            ["+82 10", "@user", "-", "=1+1", "0", "0.5"]]
    html = text_payload("", table=grid)[HTML].decode("utf-8")
    text_cells = re.findall(r"<td style='mso-number-format:\"\\@\"'>([^<]*)</td>", html)
    assert text_cells == ["007", "=SUM(A1)", "+82 10", "@user", "=1+1"]
    assert "<td>-12</td>" in html and "<td>1,250,000</td>" in html and "<td>0</td>" in html
