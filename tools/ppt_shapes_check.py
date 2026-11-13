"""도형PPT, slide by slide: every page of the PDFs goes through the app's own 도형PPT conversion twice -
from the lossless page and from the frame of a (long) screen recording - and the result is compared
with the page:

- text: the words of the PDF's text layer found in the shapes' text (recall) and the shapes' words found
  in the PDF (precision, OCR misreads lower it); also original-vs-recording;
- layout: the shapes drawn (the app's own SVG) over the page size vs the page (ink overlap, IoU);
- PowerPoint (optional, --powerpoint): the same shapes as a real .pptx, opened and exported by
  Microsoft PowerPoint, compared with the SVG drawing and the page.

    python tools/ppt_shapes_check.py PDF [PDF ...] --frames DIR/frames [--out DIR] [--powerpoint]
          [--pylib DIR]   (where python-pptx is installed, for --powerpoint)
Writes DIR/ppt_report.json, DIR/ppt_report.html and DIR/compare/slide_NN.jpg."""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
W, H = 1920, 1080
DPI = W / (960 / 72)                         # the 1920 px frame is the 13.33 in slide: 144 px per inch

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def words(text: str) -> Counter:
    t = unicodedata.normalize("NFKC", text).lower()
    return Counter(w for w in re.findall(r"[0-9a-z가-힣]+", t) if len(w) > 1 or w.isdigit())


def overlap(truth: Counter, got: Counter) -> tuple[float, float]:
    common = sum((truth & got).values())
    return (common / max(1, sum(truth.values())), common / max(1, sum(got.values())))


def pdf_pages(pdfs):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage
    from PySide6.QtPdf import QPdfDocument
    out = []
    for p in pdfs:
        d = QPdfDocument()
        d.load(p)
        for i in range(d.pageCount()):
            img = d.render(i, QSize(W, H)).convertToFormat(QImage.Format_RGB32)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine() // 4, 4)[:, :W, :3].copy()
            out.append((Path(p).name, i + 1, a, d.getAllText(i).text()))
    return out


class _Clip:
    def __init__(self):
        self.payloads = []

    def set(self, payload):
        self.payloads.append(payload)


class _Screen:
    def monitors(self):
        return []

    def cursor_pos(self):
        return (0, 0)

    def windows(self):
        return []


def make_converter(tmp: Path):
    """The app's own 도형PPT path (Controller in sync mode, the real OCR); returns convert(img) ->
    dict(shapes, conns, svg, gvml, table)."""
    from capture_tool.app import controller as ctl
    from capture_tool.core.ocr import OcrEngine
    from capture_tool.core.settings import Settings
    seen = {}
    real_to_drawing, real_panel = ctl.to_drawing, ctl.page_panel

    def spy_to_drawing(det, **kw):
        out = real_to_drawing(det, **kw)
        seen["drawing"] = out
        return out

    def spy_panel(final, keep):
        out = real_panel(final, keep)
        seen["panel"] = out
        return out
    ctl.to_drawing, ctl.page_panel = spy_to_drawing, spy_panel
    ocr = OcrEngine()
    clip = _Clip()
    c = ctl.Controller(_Screen(), clip, ocr, Settings(save_dir=str(tmp / "shots"), table_quick=True),
                       tmp / "settings.json", tmp / "fallback", sync=True)
    c.notify = lambda msg: seen.setdefault("notes", []).append(msg)

    def convert(img: np.ndarray) -> dict:
        seen.clear()
        clip.payloads.clear()
        c._run_recognition_on(np.ascontiguousarray(img), "shapes", DPI)
        from capture_tool.core.clipboard_payload import GVML, HTML, SVG
        pay = clip.payloads[-1] if clip.payloads else {}
        shapes, conns = seen.get("drawing", ([], []))
        if seen.get("panel") is not None:
            shapes = [seen["panel"]] + list(shapes)
        return {"shapes": list(shapes), "conns": list(conns), "svg": pay.get(SVG), "gvml": pay.get(GVML),
                "table_html": pay.get(HTML) if GVML not in pay else None, "notes": seen.get("notes", [])}
    return convert


def shape_text(res: dict) -> str:
    if res["table_html"] is not None:
        raw = res["table_html"].decode("utf-8", "ignore") if isinstance(res["table_html"], bytes) else res["table_html"]
        m = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", raw, re.S)     # not the CF_HTML header
        return html.unescape(re.sub(r"<[^>]+>", " ", m.group(1) if m else raw))
    return "\n".join(s.text for s in res["shapes"] if getattr(s, "text", ""))


def render_svg(res: dict) -> np.ndarray:
    """The app's SVG of the shapes, placed where the shapes are on the 1920x1080 page (white behind)."""
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from capture_tool.core.drawingml import _bounds, _resolve
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor("white"))
    if res["svg"] and res["shapes"]:
        minx, miny, maxx, maxy = _bounds(res["shapes"], _resolve(res["shapes"], res["conns"]))
        r = QSvgRenderer(QByteArray(res["svg"].encode() if isinstance(res["svg"], str) else res["svg"]))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(minx - 6, miny - 6, maxx - minx + 12, maxy - miny + 12))
        p.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine() // 4, 4)[:, :W, :3].copy()
    return a


def ink(img: np.ndarray) -> np.ndarray:
    """Where something is on the page: differs from the page's own background colour (dilated)."""
    import cv2
    small = cv2.resize(img, (480, 270), interpolation=cv2.INTER_AREA).astype(np.int16)
    bg = np.median(small.reshape(-1, 3), axis=0)
    m = (np.abs(small - bg).sum(axis=2) > 60).astype(np.uint8)
    return cv2.dilate(m, np.ones((5, 5), np.uint8)) > 0


def iou(a: np.ndarray, b: np.ndarray) -> float:
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 1.0


# --- a real .pptx and Microsoft PowerPoint -------------------------------------------------------------
def to_slide_xml(res: dict) -> list:
    """The drawing's a:sp / a:cxnSp / a:pic as p:sp / p:cxnSp / p:pic placed on the slide (lxml)."""
    from lxml import etree
    from capture_tool.core.drawingml import _bounds, _resolve, drawing_xml, px_to_emu
    if not res["shapes"] and not res["conns"]:
        return []
    shapes, conns = res["shapes"], res["conns"]
    minx, miny, _, _ = _bounds(shapes, _resolve(shapes, conns))
    root = etree.fromstring(drawing_xml(shapes, conns, DPI).encode())
    canvas = root.find(f"{{{A}}}graphicData")[0]
    dx, dy = px_to_emu(minx, DPI), px_to_emu(miny, DPI)
    out = []

    def pq(tag):
        return f"{{{P}}}{tag}"
    for el in list(canvas):
        tag = etree.QName(el).localname
        if tag not in ("sp", "cxnSp", "pic"):
            continue
        new = etree.Element(pq(tag), nsmap={"p": P, "a": A})
        for child in list(el):                     # (appending elsewhere moves them out of el)
            name = etree.QName(child).localname
            if name in ("nvSpPr", "nvCxnSpPr", "nvPicPr"):
                nv = etree.SubElement(new, pq(name))
                for sub in list(child):
                    s2 = etree.SubElement(nv, pq(etree.QName(sub).localname))
                    for k, v in sub.attrib.items():
                        s2.set(k, v)
                    for g in list(sub):
                        s2.append(g)
                etree.SubElement(nv, pq("nvPr"))
            elif name == "txSp":
                body = child.find(f"{{{A}}}txBody")
                tb = etree.SubElement(new, pq("txBody"))
                for g in list(body):
                    tb.append(g)
            elif name in ("blipFill", "spPr", "style"):      # PresentationML wrappers, DrawingML inside
                bf = etree.SubElement(new, pq(name))
                for k, v in child.attrib.items():
                    bf.set(k, v)
                for g in list(child):
                    bf.append(g)
            else:
                new.append(child)
        off = new.find(f".//{{{A}}}xfrm/{{{A}}}off")
        if off is not None:
            off.set("x", str(int(off.get("x")) + dx))
            off.set("y", str(int(off.get("y")) + dy))
        out.append((tag, new))
    return out


def build_pptx(entries: list[tuple[str, dict]], dst: Path) -> None:
    """One slide per entry (title, conversion result); pictures (icons) are dropped (none in
    these decks' shapes is a picture - counted in the report)."""
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    blank = prs.slide_layouts[6]
    for _title, res in entries:
        slide = prs.slides.add_slide(blank)
        tree = slide.shapes._spTree
        next_id = 2
        for tag, el in to_slide_xml(res):
            if tag == "pic":
                continue
            cnv = el.find(f".//{{{P}}}cNvPr")
            if cnv is not None:
                cnv.set("id", str(next_id))
            next_id += 1
            tree.append(el)
        # connectors refer to shape ids that were renumbered: drop the (cosmetic) glue
        for cx in list(tree.iter(f"{{{A}}}stCxn", f"{{{A}}}endCxn")):
            cx.getparent().remove(cx)
    prs.save(str(dst))


def quicklook_export(entries: list[tuple[str, dict]], out_dir: Path) -> list[Path]:
    """Every slide as its own .pptx, rendered by macOS's own Office reader (Quick Look) - an
    independent reader of the same XML, no Microsoft app and no permission prompt."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for title, res in entries:
        one = out_dir / f"slide_{int(title):02d}.pptx"
        build_pptx([(title, res)], one)
        subprocess.run(["qlmanage", "-t", "-s", str(W), "-o", str(out_dir), str(one)], check=True,
                       capture_output=True, timeout=120)
        out.append(out_dir / (one.name + ".png"))
    return out


def powerpoint_export(pptx: Path, out_dir: Path, timeout: int = 600) -> list[Path]:
    """Open the deck in Microsoft PowerPoint (inside its sandbox folder), save every slide as PNG,
    close only that deck. Returns the PNGs in slide order."""
    box = Path.home() / "Library/Containers/com.microsoft.Powerpoint/Data/Documents/capture-tool-check"
    box.mkdir(parents=True, exist_ok=True)
    src = box / pptx.name
    src.write_bytes(pptx.read_bytes())
    target = box / (pptx.stem + "_png")
    script = f'''
    tell application "Microsoft PowerPoint"
        open POSIX file "{src}"
        delay 2
        set p to active presentation
        save p in POSIX file "{target}" as save as PNG
        close p saving no
    end tell'''
    subprocess.run(["osascript", "-e", script], check=True, timeout=timeout, capture_output=True)
    pngs = []
    for _ in range(60):
        pngs = sorted(target.glob("*.png"), key=lambda q: int(re.findall(r"\d+", q.stem)[-1]))
        if pngs:
            break
        time.sleep(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for q in pngs:
        d = out_dir / q.name
        d.write_bytes(q.read_bytes())
        out.append(d)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--frames", required=True)
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "rec-long"))
    ap.add_argument("--powerpoint", action="store_true", help="render with Microsoft PowerPoint (asks for "
                    "permission to control it and to use its folder)")
    ap.add_argument("--quicklook", action="store_true", help="render each slide with macOS Quick Look")
    ap.add_argument("--pylib", default=str(Path(tempfile.gettempdir()) / "pylib"))
    ap.add_argument("--only", type=int, default=0, help="first N slides (a quick try)")
    ap.add_argument("--start", type=int, default=1, help="begin at this slide")
    a = ap.parse_args(argv)
    sys.path.append(a.pylib)                              # python-pptx / lxml, not a dependency of the app
    out = Path(a.out)
    (out / "compare").mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    import cv2
    pages = pdf_pages(a.pdf)
    numbered = list(enumerate(pages, 1))[a.start - 1:]
    if a.only:
        numbered = numbered[:a.only]
    convert = make_converter(Path(tempfile.mkdtemp()))
    rows, deck = [], []
    t0 = time.monotonic()
    for n, (doc, page, img, text) in numbered:
        frame_path = Path(a.frames) / f"slide_{n:02d}.png"
        frame = cv2.imread(str(frame_path)) if frame_path.exists() else None
        truth = words(text)
        row = {"slide": n, "doc": doc[:40], "page": page, "pdf_words": sum(truth.values())}
        results = {}
        for src, im in (("original", img), ("recording", frame)):
            if im is None:
                continue
            t = time.monotonic()
            res = convert(im)
            results[src] = res
            got = words(shape_text(res))
            rec, prec = overlap(truth, got)
            missing = sorted((truth - got).elements())
            row[src] = {"s": round(time.monotonic() - t, 2), "shapes": len(res["shapes"]), "conns": len(res["conns"]),
                        "text_boxes": sum(1 for s in res["shapes"] if getattr(s, "text", "")),
                        "pictures": sum(1 for s in res["shapes"] if getattr(s, "image", None)),
                        "table": res["table_html"] is not None, "recall": round(rec, 3), "precision": round(prec, 3),
                        "missing": missing[:25]}
            drawn = render_svg(res) if res["table_html"] is None else np.full_like(img, 255)
            row[src]["layout_iou"] = round(iou(ink(img), ink(drawn)), 3)
            res["drawn"] = drawn
        if "original" in results and "recording" in results:
            g1, g2 = words(shape_text(results["original"])), words(shape_text(results["recording"]))
            row["orig_vs_rec_words"] = round(overlap(g1, g2)[0], 3)
        rows.append(row)
        best = results.get("recording") or results.get("original")
        deck.append((f"{n}", best))
        print(f"slide {n:2d}  " + "  ".join(
            f"{s}: recall {row[s]['recall']:.2f} prec {row[s]['precision']:.2f} iou {row[s]['layout_iou']:.2f}"
            for s in ("original", "recording") if s in row), flush=True)
        # comparison sheet: page | recorded frame / shapes (SVG) | PowerPoint (filled in later)
        top = np.hstack([img, frame if frame is not None else np.full_like(img, 200)])
        bottom = np.hstack([best["drawn"], np.full_like(img, 235)])
        sheet = cv2.resize(np.vstack([top, bottom]), (1280, 720), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(out / "compare" / f"slide_{n:02d}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 82])
    report = {"slides": rows, "convert_s": round(time.monotonic() - t0, 1)}
    if a.powerpoint or a.quicklook:
        pptx = out / "shapes_check.pptx"
        build_pptx(deck, pptx)
        report["pptx"] = str(pptx)
        report["renderer"] = "Microsoft PowerPoint" if a.powerpoint else "macOS Quick Look"
        try:
            pngs = (powerpoint_export(pptx, out / "powerpoint") if a.powerpoint
                    else quicklook_export(deck, out / "quicklook"))
        except Exception as e:  # noqa: BLE001 - reported; the rest of the check stands
            report["powerpoint_error"] = str(e)
            pngs = []
        report["powerpoint_slides"] = len(pngs)
        for row, (_, res), png in zip(rows, deck, pngs):
            ppt = cv2.resize(cv2.imread(str(png)), (W, H), interpolation=cv2.INTER_AREA)
            orig = pages[row["slide"] - 1][2]
            row["powerpoint"] = {"iou_vs_shapes_svg": round(iou(ink(res["drawn"]), ink(ppt)), 3),
                                 "iou_vs_page": round(iou(ink(orig), ink(ppt)), 3)}
            sheet_path = out / "compare" / f"slide_{row['slide']:02d}.jpg"
            frame = cv2.imread(str(Path(a.frames) / f"slide_{row['slide']:02d}.png"))
            top = np.hstack([orig, frame if frame is not None else np.full_like(orig, 200)])
            bottom = np.hstack([res["drawn"], ppt])
            cv2.imwrite(str(sheet_path), cv2.resize(np.vstack([top, bottom]), (1280, 720), interpolation=cv2.INTER_AREA),
                        [cv2.IMWRITE_JPEG_QUALITY, 82])
    json.dump(report, open(out / "ppt_report.json", "w"), indent=1, ensure_ascii=False)
    write_html(report, out)
    return 0


def write_html(report: dict, out: Path) -> None:
    def cell(r, s, k):
        return f"{r[s][k]:.2f}" if s in r else "-"
    trs = []
    for r in report["slides"]:
        ppt = r.get("powerpoint", {})
        miss = ", ".join(r.get("recording", r.get("original", {})).get("missing", [])[:12])
        trs.append(
            f"<tr><td>{r['slide']}</td><td>{html.escape(r['doc'][:18])} p{r['page']}</td><td>{r['pdf_words']}</td>"
            f"<td>{cell(r, 'original', 'recall')}</td><td>{cell(r, 'recording', 'recall')}</td>"
            f"<td>{cell(r, 'recording', 'precision')}</td><td>{r.get('orig_vs_rec_words', '-')}</td>"
            f"<td>{cell(r, 'recording', 'layout_iou')}</td><td>{ppt.get('iou_vs_shapes_svg', '-')}</td>"
            f"<td>{html.escape(miss)}</td>"
            f"<td><a href='compare/slide_{r['slide']:02d}.jpg'><img src='compare/slide_{r['slide']:02d}.jpg' width=320></a></td></tr>")
    page = ("<html><meta charset='utf-8'><style>body{font-family:sans-serif}td,th{border:1px solid #ccc;padding:3px;"
            "font-size:12px;vertical-align:top}table{border-collapse:collapse}</style>"
            "<h2>도형PPT 장별 비교</h2><p>그림: 왼쪽 위 원본 페이지 · 오른쪽 위 녹화 영상의 장면 · 왼쪽 아래 도형PPT 결과(앱의 SVG) · "
            "오른쪽 아래 그 도형을 .pptx 로 만들어 Office 문서 렌더러가 그린 결과</p><table><tr><th>#</th><th>문서</th><th>PDF 낱말</th><th>원본 재현율</th>"
            "<th>녹화 재현율</th><th>녹화 정확도</th><th>원본=녹화</th><th>배치 IoU</th><th>pptx=도형</th><th>빠진 낱말</th>"
            "<th>비교</th></tr>" + "".join(trs) + "</table></html>")
    (out / "ppt_report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
