import io
import zipfile
import xml.etree.ElementTree as ET

import pytest

from capture_tool.core.drawingml import (
    DConnector,
    DShape,
    connection_sites,
    drawing_xml,
    gvml_package,
    px_to_emu,
    svg,
)

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "lc": "http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas",
}


def flow():
    shapes = [
        DShape("roundRect", 20, 40, 150, 64, text="요청 접수"),
        DShape("roundRect", 240, 40, 150, 64, text="검토"),
        DShape("roundRect", 460, 40, 150, 64, text="승인"),
        DShape("roundRect", 240, 210, 150, 64, text="반려 처리"),
    ]
    conns = [DConnector(start=0, end=1), DConnector(start=1, end=2), DConnector(start=1, end=3)]
    return shapes, conns


def parse(xml):
    return ET.fromstring(xml.encode("utf-8"))


def test_DML_01_px_to_emu():
    assert px_to_emu(1) == 9525
    assert px_to_emu(96) == 914400
    assert px_to_emu(2, dpi=192) == 9525


def test_DML_02_counts():
    root = parse(drawing_xml(*flow()))
    assert len(root.findall(".//a:sp", NS)) == 4
    assert len(root.findall(".//a:cxnSp", NS)) == 3


@pytest.mark.parametrize("kind", ["rect", "roundRect", "ellipse", "triangle"])
def test_DML_03_geometry_mapping(kind):
    root = parse(drawing_xml([DShape(kind, 0, 0, 10, 10)], []))
    assert root.find(".//a:prstGeom", NS).get("prst") == kind


def test_DML_03b_unknown_kind():
    with pytest.raises(ValueError):
        DShape("star", 0, 0, 10, 10)


def test_DML_04_text_inside_shape():
    root = parse(drawing_xml(*flow()))
    sp = root.findall(".//a:sp", NS)[0]
    assert sp.find("a:txSp//a:t", NS).text == "요청 접수"


def test_DML_05_special_chars_escaped():
    xml = drawing_xml([DShape("rect", 0, 0, 10, 10, text='a<b & "c">')], [])
    assert parse(xml).find(".//a:t", NS).text == 'a<b & "c">'


def test_DML_05b_control_chars_removed():
    xml = drawing_xml([DShape("rect", 0, 0, 10, 10, text="a\x01b\x0bc")], [])
    assert parse(xml).find(".//a:t", NS).text == "abc"


def test_DML_06_korean_and_emoji_preserved():
    xml = drawing_xml([DShape("rect", 0, 0, 10, 10, text="검토 ✅🚀")], [])
    assert parse(xml).find(".//a:t", NS).text == "검토 ✅🚀"


def test_DML_07_no_fill():
    root = parse(drawing_xml([DShape("rect", 0, 0, 10, 10, fill=None)], []))
    assert root.find(".//a:sp/a:spPr/a:noFill", NS) is not None


def test_DML_08_connectors_reference_ids_and_arrow():
    root = parse(drawing_xml(*flow()))
    ids = [sp.find("a:nvSpPr/a:cNvPr", NS).get("id") for sp in root.findall(".//a:sp", NS)]
    all_ids = ids + [c.find("a:nvCxnSpPr/a:cNvPr", NS).get("id") for c in root.findall(".//a:cxnSp", NS)]
    assert len(set(all_ids)) == len(all_ids)
    c0 = root.findall(".//a:cxnSp", NS)[0]
    assert c0.find(".//a:stCxn", NS).get("id") == ids[0]
    assert c0.find(".//a:endCxn", NS).get("id") == ids[1]
    assert c0.find(".//a:ln/a:tailEnd", NS).get("type") == "triangle"


def test_DML_09_connection_sites():
    a = DShape("rect", 0, 0, 100, 50)
    right = DShape("rect", 300, 0, 100, 50)
    below = DShape("rect", 0, 300, 100, 50)
    assert connection_sites(a, right) == (3, 1)
    assert connection_sites(right, a) == (1, 3)
    assert connection_sites(a, below) == (2, 0)
    assert connection_sites(below, a) == (0, 2)


def test_DML_09b_connector_endpoints_on_sites_and_flip():
    shapes = [DShape("rect", 300, 0, 100, 50), DShape("rect", 0, 0, 100, 50)]
    root = parse(drawing_xml(shapes, [DConnector(start=0, end=1)]))
    xfrm = root.find(".//a:cxnSp/a:spPr/a:xfrm", NS)
    assert xfrm.get("flipH") == "1"
    assert int(xfrm.find("a:ext", NS).get("cx")) == px_to_emu(200)


def test_DML_10_negative_coordinates_normalized():
    root = parse(drawing_xml([DShape("rect", -50, -20, 10, 10), DShape("rect", 100, 100, 10, 10)], []))
    offs = [int(o.get(k)) for o in root.findall(".//a:sp//a:off", NS) for k in ("x", "y")]
    assert min(offs) == 0
    grp = root.find(".//lc:lockedCanvas/a:grpSpPr/a:xfrm", NS)
    assert int(grp.find("a:ext", NS).get("cx")) == px_to_emu(160)


def test_DML_11_empty():
    with pytest.raises(ValueError):
        drawing_xml([], [])


def test_DML_12_zero_size_shape():
    with pytest.raises(ValueError):
        DShape("rect", 0, 0, 0, 10)


def test_DML_12b_bad_connector_index():
    with pytest.raises(ValueError):
        drawing_xml([DShape("rect", 0, 0, 10, 10)], [DConnector(start=0, end=5)])


def test_DML_13_package_structure():
    data = gvml_package(*flow())
    z = zipfile.ZipFile(io.BytesIO(data))
    assert set(z.namelist()) == {"[Content_Types].xml", "_rels/.rels", "clipboard/drawings/drawing1.xml"}
    assert b"drawing+xml" in z.read("[Content_Types].xml")
    parse(z.read("clipboard/drawings/drawing1.xml").decode("utf-8"))


def test_DML_14_svg_fallback():
    s = svg(*flow())
    root = ET.fromstring(s.encode("utf-8"))
    tags = [el.tag.split("}")[1] for el in root.iter()]
    assert tags.count("rect") == 4
    assert tags.count("polygon") == 3  # arrowheads as real polygons
    assert "반려 처리" in s


def test_DML_15_free_arrow_without_targets():
    root = parse(drawing_xml([DShape("rect", 0, 0, 10, 10)], [DConnector(x1=50, y1=50, x2=150, y2=50)]))
    c = root.find(".//a:cxnSp", NS)
    assert c.find(".//a:stCxn", NS) is None
    assert c.find(".//a:tailEnd", NS) is not None


def test_plain_line_has_no_arrowhead():
    root = parse(drawing_xml([DShape("rect", 0, 0, 10, 10)], [DConnector(x1=0, y1=50, x2=100, y2=50, arrow=False)]))
    assert root.find(".//a:cxnSp//a:tailEnd", NS) is None


def test_DML_16_text_formatting():
    s = DShape("rect", 0, 0, 100, 40, text="강조", font_size=18, bold=True, italic=True, underline=True, strike=True)
    rpr = parse(drawing_xml([s], [])).find(".//a:rPr", NS)
    assert (rpr.get("sz"), rpr.get("b"), rpr.get("i"), rpr.get("u"), rpr.get("strike")) == \
        ("1800", "1", "1", "sng", "sngStrike")


def test_DML_18_font_family_in_powerpoint_and_svg():
    s = DShape("rect", 0, 0, 100, 40, text="가", font_family='궁서 "A&B"')
    rpr = parse(drawing_xml([s], [])).find(".//a:rPr", NS)
    assert rpr.find("a:latin", NS).get("typeface") == '궁서 "A&B"'
    assert rpr.find("a:ea", NS).get("typeface") == '궁서 "A&B"'
    root = ET.fromstring(svg([s], []).encode("utf-8"))
    text = [el for el in root.iter() if el.tag.endswith("text")][0]
    assert text.get("font-family").startswith('궁서 "A&B"')


def test_DML_18b_default_font_left_to_theme():
    rpr = parse(drawing_xml([DShape("rect", 0, 0, 100, 40, text="가")], [])).find(".//a:rPr", NS)
    assert rpr.find("a:latin", NS) is None


def test_DML_17_same_size_on_high_dpi_screens():
    """150 physical px on a 150% screen are 100 logical px = 100/96 inch on screen."""
    root = parse(drawing_xml([DShape("rect", 0, 0, 150, 60)], [], dpi=144))
    ext = root.find(".//a:sp//a:ext", NS)
    assert int(ext.get("cx")) == px_to_emu(100) and int(ext.get("cy")) == px_to_emu(40)
    s = svg([DShape("rect", 0, 0, 150, 60)], [], dpi=144)
    root_svg = ET.fromstring(s.encode())
    assert root_svg.get("width") == "81pt"   # (150 + 2*6 padding) px at 144 dpi, in points
    assert root_svg.get("viewBox") == "0 0 162 72"   # drawing coordinates stay in pixels


def test_colors_written():
    root = parse(drawing_xml([DShape("rect", 0, 0, 10, 10, fill="#f1f3f5", stroke="#343a40")], []))
    vals = [c.get("val") for c in root.findall(".//a:sp/a:spPr//a:srgbClr", NS)]
    assert vals == ["F1F3F5", "343A40"]
