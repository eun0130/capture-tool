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


def test_dib_from_bgra_and_gray():
    assert len(dib_from_bgr(np.zeros((2, 2, 4), np.uint8))) == 40 + 16
    assert len(dib_from_bgr(np.zeros((2, 2), np.uint8))) == 40 + 16
