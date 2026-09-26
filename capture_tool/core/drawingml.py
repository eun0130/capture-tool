"""Shapes -> Office "Art::GVML ClipFormat" (DrawingML lockedCanvas zip).

Pasting this clipboard format into PowerPoint 365 yields native, editable shapes:
text lives inside the shape and connectors stay glued to shapes (verified by spike,
2026-09-26). An SVG rendering is produced as a fallback for other apps."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .color import normalize_hex

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
LC_NS = "http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas"
KINDS = ("rect", "roundRect", "ellipse", "triangle")
TOP, LEFT, BOTTOM, RIGHT = "top", "left", "bottom", "right"
# PowerPoint connection-site indexes per geometry
_SITE_IDX = {
    "rect": {TOP: 0, LEFT: 1, BOTTOM: 2, RIGHT: 3},
    "roundRect": {TOP: 0, LEFT: 1, BOTTOM: 2, RIGHT: 3},
    "ellipse": {TOP: 0, LEFT: 2, BOTTOM: 4, RIGHT: 6},
    "triangle": {TOP: 0, LEFT: 1, BOTTOM: 3, RIGHT: 5},
}
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def px_to_emu(px: float, dpi: float = 96) -> int:
    return round(px * 914400 / dpi)


@dataclass
class DShape:
    kind: str
    x: float
    y: float
    w: float
    h: float
    fill: str | None = "#FFFFFF"
    stroke: str | None = "#000000"
    stroke_width: float = 2
    text: str | None = None
    text_color: str = "#000000"
    font_size: float = 14
    bold: bool = False

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unsupported shape kind: {self.kind!r}")
        if self.w <= 0 or self.h <= 0:
            raise ValueError("shape width and height must be > 0")
        self.fill = normalize_hex(self.fill) if self.fill else None
        self.stroke = normalize_hex(self.stroke) if self.stroke else None
        self.text_color = normalize_hex(self.text_color)

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def site_point(self, side: str) -> tuple[float, float]:
        if self.kind == "triangle":
            return {
                TOP: (self.cx, self.y),
                LEFT: (self.x + self.w / 4, self.cy),
                BOTTOM: (self.cx, self.y + self.h),
                RIGHT: (self.x + 3 * self.w / 4, self.cy),
            }[side]
        return {
            TOP: (self.cx, self.y),
            LEFT: (self.x, self.cy),
            BOTTOM: (self.cx, self.y + self.h),
            RIGHT: (self.x + self.w, self.cy),
        }[side]


@dataclass
class DConnector:
    start: int | None = None
    end: int | None = None
    x1: float = 0
    y1: float = 0
    x2: float = 0
    y2: float = 0
    color: str = "#000000"
    width: float = 2
    arrow: bool = True


def _sides(a: DShape, b: DShape) -> tuple[str, str]:
    dx, dy = b.cx - a.cx, b.cy - a.cy
    if abs(dx) >= abs(dy):
        return (RIGHT, LEFT) if dx >= 0 else (LEFT, RIGHT)
    return (BOTTOM, TOP) if dy > 0 else (TOP, BOTTOM)


def connection_sites(a: DShape, b: DShape) -> tuple[int, int]:
    sa, sb = _sides(a, b)
    return _SITE_IDX[a.kind][sa], _SITE_IDX[b.kind][sb]


@dataclass
class _Line:
    x1: float
    y1: float
    x2: float
    y2: float
    st: tuple[int, int] | None  # (shape index, site idx)
    en: tuple[int, int] | None
    c: DConnector


def _resolve(shapes: list[DShape], conns: list[DConnector]) -> list[_Line]:
    out = []
    for c in conns:
        for ref in (c.start, c.end):
            if ref is not None and not 0 <= ref < len(shapes):
                raise ValueError(f"connector refers to missing shape {ref}")
        x1, y1, x2, y2 = c.x1, c.y1, c.x2, c.y2
        st = en = None
        if c.start is not None and c.end is not None:
            a, b = shapes[c.start], shapes[c.end]
            sa, sb = _sides(a, b)
            (x1, y1), (x2, y2) = a.site_point(sa), b.site_point(sb)
            st, en = (c.start, _SITE_IDX[a.kind][sa]), (c.end, _SITE_IDX[b.kind][sb])
        out.append(_Line(x1, y1, x2, y2, st, en, c))
    return out


def _bounds(shapes, lines):
    xs = [s.x for s in shapes] + [s.x + s.w for s in shapes] + [v for l in lines for v in (l.x1, l.x2)]
    ys = [s.y for s in shapes] + [s.y + s.h for s in shapes] + [v for l in lines for v in (l.y1, l.y2)]
    return min(xs), min(ys), max(xs), max(ys)


def _clean(text: str) -> str:
    return _CTRL.sub("", text)


def _fill(color):
    return f'<a:solidFill><a:srgbClr val="{color[1:]}"/></a:solidFill>' if color else "<a:noFill/>"


def _ln(color, width_px, arrow=False):
    if not color:
        return "<a:ln><a:noFill/></a:ln>"
    tail = '<a:tailEnd type="triangle"/>' if arrow else ""
    return f'<a:ln w="{px_to_emu(width_px)}">{_fill(color)}{tail}</a:ln>'


def _txbody(s: DShape) -> str:
    if not s.text:
        return ""
    paras = []
    for line in _clean(s.text).split("\n"):
        b = ' b="1"' if s.bold else ""
        paras.append(
            f'<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="ko-KR" sz="{round(s.font_size * 100)}"{b}>'
            f'{_fill(s.text_color)}</a:rPr><a:t>{escape(line)}</a:t></a:r></a:p>'
        )
    return (f'<a:txSp><a:txBody><a:bodyPr anchor="ctr" wrap="square"/><a:lstStyle/>{"".join(paras)}'
            f"</a:txBody><a:useSpRect/></a:txSp>")


def drawing_xml(shapes: list[DShape], connectors: list[DConnector]) -> str:
    if not shapes and not connectors:
        raise ValueError("nothing to draw")
    lines = _resolve(shapes, connectors)
    minx, miny, maxx, maxy = _bounds(shapes, lines)
    e = lambda v, o: px_to_emu(v - o)  # noqa: E731
    ids = {i: i + 2 for i in range(len(shapes))}
    parts = []
    for i, s in enumerate(shapes):
        parts.append(
            f'<a:sp><a:nvSpPr><a:cNvPr id="{ids[i]}" name="{s.kind} {i + 1}"/><a:cNvSpPr/></a:nvSpPr>'
            f'<a:spPr><a:xfrm><a:off x="{e(s.x, minx)}" y="{e(s.y, miny)}"/>'
            f'<a:ext cx="{px_to_emu(s.w)}" cy="{px_to_emu(s.h)}"/></a:xfrm>'
            f'<a:prstGeom prst="{s.kind}"><a:avLst/></a:prstGeom>{_fill(s.fill)}{_ln(s.stroke, s.stroke_width)}</a:spPr>'
            f"{_txbody(s)}</a:sp>"
        )
    next_id = len(shapes) + 2
    for j, l in enumerate(lines):
        cid = next_id + j
        cx = ""
        if l.st and l.en:
            cx = f'<a:stCxn id="{ids[l.st[0]]}" idx="{l.st[1]}"/><a:endCxn id="{ids[l.en[0]]}" idx="{l.en[1]}"/>'
        flip = (' flipH="1"' if l.x2 < l.x1 else "") + (' flipV="1"' if l.y2 < l.y1 else "")
        parts.append(
            f'<a:cxnSp><a:nvCxnSpPr><a:cNvPr id="{cid}" name="connector {j + 1}"/>'
            f"<a:cNvCxnSpPr>{cx}</a:cNvCxnSpPr></a:nvCxnSpPr>"
            f'<a:spPr><a:xfrm{flip}><a:off x="{e(min(l.x1, l.x2), minx)}" y="{e(min(l.y1, l.y2), miny)}"/>'
            f'<a:ext cx="{px_to_emu(abs(l.x2 - l.x1))}" cy="{px_to_emu(abs(l.y2 - l.y1))}"/></a:xfrm>'
            f'<a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom>'
            f"{_ln(normalize_hex(l.c.color), l.c.width, l.c.arrow)}</a:spPr></a:cxnSp>"
        )
    W, H = px_to_emu(maxx - minx), px_to_emu(maxy - miny)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<a:graphic xmlns:a="{A_NS}"><a:graphicData uri="{LC_NS}"><lc:lockedCanvas xmlns:lc="{LC_NS}">'
        '<a:nvGrpSpPr><a:cNvPr id="1" name="capture"/><a:cNvGrpSpPr/></a:nvGrpSpPr>'
        f'<a:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W}" cy="{H}"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="{W}" cy="{H}"/></a:xfrm></a:grpSpPr>'
        + "".join(parts)
        + "</lc:lockedCanvas></a:graphicData></a:graphic>"
    )


_CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/clipboard/drawings/drawing1.xml" '
       'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
         'Target="clipboard/drawings/drawing1.xml"/></Relationships>')


def gvml_package(shapes: list[DShape], connectors: list[DConnector]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("clipboard/drawings/drawing1.xml", drawing_xml(shapes, connectors))
    return buf.getvalue()


def svg(shapes: list[DShape], connectors: list[DConnector]) -> str:
    if not shapes and not connectors:
        raise ValueError("nothing to draw")
    lines = _resolve(shapes, connectors)
    minx, miny, maxx, maxy = _bounds(shapes, lines)
    pad = 6
    ox, oy = minx - pad, miny - pad
    W, H = maxx - minx + 2 * pad, maxy - miny + 2 * pad
    f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{f(W)}" height="{f(H)}" viewBox="0 0 {f(W)} {f(H)}">']
    for s in shapes:
        x, y = s.x - ox, s.y - oy
        style = f'fill="{s.fill or "none"}" stroke="{s.stroke or "none"}" stroke-width="{f(s.stroke_width)}"'
        if s.kind in ("rect", "roundRect"):
            rx = f' rx="{f(min(s.w, s.h) * 0.16)}"' if s.kind == "roundRect" else ""
            out.append(f'<rect x="{f(x)}" y="{f(y)}" width="{f(s.w)}" height="{f(s.h)}"{rx} {style}/>')
        elif s.kind == "ellipse":
            out.append(f'<ellipse cx="{f(x + s.w / 2)}" cy="{f(y + s.h / 2)}" rx="{f(s.w / 2)}" ry="{f(s.h / 2)}" {style}/>')
        else:
            pts = f"{f(x + s.w / 2)},{f(y)} {f(x)},{f(y + s.h)} {f(x + s.w)},{f(y + s.h)}"
            out.append(f'<polygon points="{pts}" {style}/>')
        if s.text:
            weight = ' font-weight="bold"' if s.bold else ""
            out.append(
                f'<text x="{f(x + s.w / 2)}" y="{f(y + s.h / 2)}" text-anchor="middle" dominant-baseline="central" '
                f'font-family="Malgun Gothic, sans-serif" font-size="{f(s.font_size * 96 / 72)}"{weight} '
                f'fill="{s.text_color}">{escape(_clean(s.text))}</text>'
            )
    for l in lines:
        color = normalize_hex(l.c.color)
        x1, y1, x2, y2 = l.x1 - ox, l.y1 - oy, l.x2 - ox, l.y2 - oy
        if l.c.arrow:
            dx, dy = x2 - x1, y2 - y1
            n = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            ux, uy = dx / n, dy / n
            size = 4 * l.c.width + 4
            bx, by = x2 - ux * size, y2 - uy * size
            half = size * 0.5
            out.append(f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(bx)}" y2="{f(by)}" stroke="{color}" stroke-width="{f(l.c.width)}"/>')
            out.append(f'<polygon points="{f(x2)},{f(y2)} {f(bx - uy * half)},{f(by + ux * half)} '
                       f'{f(bx + uy * half)},{f(by - ux * half)}" fill="{color}"/>')
        else:
            out.append(f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="{color}" stroke-width="{f(l.c.width)}"/>')
    out.append("</svg>")
    return "".join(out)
