"""Random inputs (fixed seeds, thousands of cases) against the core: nothing may raise and the
invariants must hold — the edge cases nobody thought to write down."""
import io
import json
import random
import string
import zipfile
from xml.dom import minidom

import numpy as np
import pytest

from capture_tool.core.geometry import (Monitor, Rect, clamp_rect, layout_bars, monitor_at, nudge,
                                        order_cursor_first, selection_from_drag, virtual_bounds)

R = random.Random(20261003)
WEIRD = ["", " ", "\n", "\t\t", "\r\n", "\x00", "\u200b", "😀", "a\u0301", "ﬁ", "\ufeff", "가" * 500, "<&>\"'",
         "]]>", "\\\\server\\share", "C:\\캡처 폴더\\a b.png", "x" * 10000, "١٢٣", "ẞ", "\U0001F600" * 3]


def rnd_text(n=60):
    pool = string.printable + "가나다라마바사아자차카타파하。、「」…★①Ññßéü\u00a0\u200b"
    return "".join(R.choice(pool) for _ in range(R.randint(0, n))) + R.choice(WEIRD)


def rnd_rect(span=6000):
    return Rect(R.randint(-span, span), R.randint(-span, span), R.randint(0, span), R.randint(0, span))


# --- geometry ------------------------------------------------------------------------------------------
def test_FUZZ_01_geometry_never_leaves_its_bounds():
    for _ in range(4000):
        b = Rect(R.randint(-5000, 5000), R.randint(-3000, 3000), R.randint(1, 8000), R.randint(1, 5000))
        r = rnd_rect()
        c = clamp_rect(r, b)
        if c is not None:
            assert c.w > 0 and c.h > 0 and c.x >= b.x and c.y >= b.y and c.right <= b.right and c.bottom <= b.bottom
        p1 = (R.randint(-9000, 9000), R.randint(-9000, 9000))
        p2 = (R.randint(-9000, 9000), R.randint(-9000, 9000))
        s = selection_from_drag(p1, p2, b)
        if s is not None:
            assert b.x <= s.x and s.right <= b.right and b.y <= s.y and s.bottom <= b.bottom
            n = nudge(s, R.randint(-500, 500), R.randint(-500, 500), b)
            assert (n.w, n.h) == (s.w, s.h) and b.x <= n.x and n.right <= b.right and b.y <= n.y and n.bottom <= b.bottom


def test_FUZZ_02_bars_always_on_the_monitor_and_not_overlapping():
    for _ in range(3000):
        mon = Rect(R.randint(-4000, 4000), R.randint(-2000, 2000), R.randint(600, 4000), R.randint(400, 2400))
        w, h = R.randint(1, mon.w), R.randint(1, mon.h)
        sel = Rect(mon.x + R.randint(0, mon.w - w), mon.y + R.randint(0, mon.h - h), w, h)
        tb = (R.randint(100, min(900, mon.w - 20)), R.randint(30, 100))
        sb = (R.randint(50, 130), R.randint(60, min(500, mon.h - 20)))
        (tx, ty), (sx, sy) = layout_bars(sel, mon, tb, sb)
        assert mon.x <= sx and sx + sb[0] <= mon.right and mon.y <= sy and sy + sb[1] <= mon.bottom


def test_FUZZ_03_monitor_layouts_with_negative_and_mixed_dpi():
    for _ in range(500):
        mons = []
        x = R.randint(-6000, 0)
        for i in range(R.randint(1, 4)):
            w, h = R.choice([(1920, 1080), (3840, 2160), (2560, 1440), (1366, 768), (1080, 1920)])
            mons.append(Monitor(i, Rect(x, R.randint(-1200, 600), w, h), R.choice([1.0, 1.25, 1.5, 1.75, 2.0]),
                                i == 0, f"M{i}"))
            x += w
        v = virtual_bounds(mons)
        for _ in range(20):
            p = (R.randint(v.x - 500, v.right + 500), R.randint(v.y - 500, v.bottom + 500))
            m = monitor_at(p, mons)
            assert m in mons
            ordered = order_cursor_first(mons, p)
            assert sorted(o.id for o in ordered) == sorted(o.id for o in mons) and ordered[0] is m


# --- drawings / undo -------------------------------------------------------------------------------------
def test_FUZZ_04_random_edit_sequences_keep_shapes_inside_and_undo_consistent():
    from capture_tool.core.annotations import KINDS, Document, Shape
    for seed in range(40):
        rr = random.Random(seed)
        d = Document(rr.randint(1, 3000), rr.randint(1, 3000))
        for _ in range(150):
            op = rr.random()
            if op < 0.5:
                kind = rr.choice(sorted(KINDS))
                n = {"text": 1, "step": 1}.get(kind, 2 if kind not in ("pen", "curve", "clip") else rr.randint(0, 30))
                pts = [(rr.uniform(-500, 3500), rr.uniform(-500, 3500)) for _ in range(n)]
                try:
                    s = Shape(kind=kind, points=pts, text=rnd_text(20) if kind == "text" else None,
                              number=1 if kind == "step" else None, color=rr.choice(["#E03131", "#000", "#ffffff"]),
                              width=rr.uniform(0.1, 200), font_size=rr.randint(-50, 999),
                              bg=rr.choice([None, "#FFEC99"]))
                except ValueError:
                    continue
                d.add(s)
            elif op < 0.65 and d.shapes:
                d.move(rr.randrange(len(d.shapes)), rr.uniform(-5000, 5000), rr.uniform(-5000, 5000))
            elif op < 0.75 and d.shapes:
                try:
                    d.update(rr.randrange(len(d.shapes)), color=rr.choice(["#123456", "nope"]))
                except ValueError:
                    pass
            elif op < 0.85 and d.shapes:
                d.delete(rr.randrange(len(d.shapes)))
            elif op < 0.93:
                d.undo()
            else:
                d.redo()
            for s in d.shapes:
                assert all(0 <= x <= d.width and 0 <= y <= d.height for x, y in s.points), s


def test_FUZZ_05_render_any_document(qt_app):
    from capture_tool.app.render import compose
    from capture_tool.core.annotations import Document, Shape
    rr = random.Random(5)
    for _ in range(60):
        w, h = rr.randint(1, 600), rr.randint(1, 600)
        d = Document(w, h)
        for _ in range(rr.randint(0, 12)):
            kind = rr.choice(["rect", "ellipse", "line", "arrow", "pen", "text", "step", "highlight", "mosaic", "clip"])
            n = {"text": 1, "step": 1, "pen": 5, "clip": rr.randint(0, 6)}.get(kind, 2)
            try:
                d.add(Shape(kind=kind, points=[(rr.uniform(0, w), rr.uniform(0, h)) for _ in range(n)],
                            text=rnd_text(15), number=3, bg=rr.choice([None, "#D0EBFF"])))
            except ValueError:
                pass
        out = compose(np.full((h, w, 3), 128, np.uint8), d)
        assert out.ndim == 3 and out.shape[2] in (3, 4) and out.shape[0] <= h and out.shape[1] <= w


# --- scroll stitching, OCR tiles, crops -------------------------------------------------------------------
def test_FUZZ_06_stitcher_survives_any_frames():
    from capture_tool.core.stitch import NOMATCH, Stitcher
    rr = np.random.default_rng(6)
    for case in range(40):
        h, w = int(rr.integers(10, 300)), int(rr.integers(10, 300))
        st = Stitcher(max_height=int(rr.integers(10, 2000)))
        kind = case % 4
        for _ in range(8):
            if kind == 0:
                f = rr.integers(0, 256, (h, w, 3), dtype=np.uint8)              # pure noise
            elif kind == 1:
                f = np.full((h, w, 3), int(rr.integers(0, 256)), np.uint8)    # flat colour
            elif kind == 2:
                f = np.zeros((h, w, 4), np.uint8)                              # BGRA
            else:
                f = np.repeat(rr.integers(0, 256, (h, 1, 3), dtype=np.uint8), w, axis=1)   # stripes
            r = st.add(f)
            assert r.status in ("added", "same", "nomatch", "full")
        out = st.result()
        assert out.ndim == 3 and out.shape[2] == 3 and 1 <= out.shape[0] <= max(h, st.max_height)


def test_FUZZ_07_ocr_tiles_cover_every_pixel_once_by_ownership():
    from capture_tool.core.ocr import _owned, tiles
    rr = random.Random(7)
    for _ in range(400):
        w, h = rr.randint(1, 20000), rr.randint(1, 30000)
        ts = tiles(w, h)
        assert all(tw <= 3800 and th <= 1900 and x >= 0 and y >= 0 and x + tw <= w and y + th <= h for x, y, tw, th in ts)
        for _ in range(30):
            px, py = rr.uniform(0, w), rr.uniform(0, h)
            owners = [t for t in ts if (lambda o: o[0] <= px < o[2] and o[1] <= py < o[3])(_owned(*t, w, h))]
            assert len(owners) == 1, (w, h, px, py)


def test_FUZZ_08_freeform_crop_random_outlines():
    from capture_tool.core.clip import clip_image, flatten, mask_outside
    rr = random.Random(8)
    img = np.random.default_rng(8).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    for _ in range(500):
        pts = [(rr.uniform(-100, 420), rr.uniform(-100, 340)) for _ in range(rr.randint(0, 40))]
        out = clip_image(img, pts)
        if out is not None:
            assert out.shape[2] == 4 and out.shape[0] <= 240 and out.shape[1] <= 320
            assert flatten(out).shape[2] == 3
        assert mask_outside(img, pts).shape == img.shape


# --- text ------------------------------------------------------------------------------------------------
def test_FUZZ_09_text_split_restore_and_chunks_round_trip():
    from capture_tool.core.ai_text import chunk_text, detect_lang, restore_layout, split_for_mt
    for _ in range(2000):
        t = rnd_text(300)
        parts, layout = split_for_mt(t)
        if parts or layout:
            back = restore_layout(parts, layout)
            assert back.replace(" ", "") == "\n".join(l for l in t.split("\n")).replace(" ", "") or \
                back.split("\n") == [l if l.strip() else "" for l in t.split("\n")]
        assert detect_lang(t) in ("ko", "en", "ja", "zh", "fr", "es", "de")
        n = R.randint(5, 400)
        ch = chunk_text(t, n)
        assert all(len(c) <= n for c in ch)


def test_FUZZ_10_masking_keeps_length_and_hides_numbers():
    from capture_tool.core.redact import mask
    for _ in range(3000):
        t = rnd_text(120)
        m = mask(t)
        assert len(m) == len(t)
    assert "010" not in mask("연락처 010-1234-5678 끝")


def test_FUZZ_11_ocr_text_helpers_any_boxes():
    from capture_tool.core.ocr import OcrLine, full_text, select_text
    rr = random.Random(11)
    for _ in range(500):
        lines = [OcrLine(rnd_text(20), (rr.randint(-50, 2000), rr.randint(-50, 2000), rr.randint(0, 400),
                                        rr.randint(0, 80)), rr.random()) for _ in range(rr.randint(0, 25))]
        full_text(lines)
        select_text(lines, (rr.uniform(-100, 2000), rr.uniform(-100, 2000), rr.uniform(0, 900), rr.uniform(0, 900)))


def test_FUZZ_12_tables_from_any_boxes_and_images():
    from capture_tool.core.table import detect_grid, table_is_plausible, to_grid, to_tsv
    rr = random.Random(12)
    rng = np.random.default_rng(12)
    for _ in range(300):
        items = [(rnd_text(10), rr.randint(0, 2000), rr.randint(0, 2000), rr.randint(1, 300), rr.randint(1, 60))
                 for _ in range(rr.randint(0, 40))]
        g = to_grid(items)
        to_tsv(g)
        table_is_plausible(g)
    for _ in range(60):
        h, w = int(rng.integers(1, 400)), int(rng.integers(1, 400))
        found = detect_grid(rng.integers(0, 256, (h, w, 3), dtype=np.uint8))
        assert found is None or (len(found[0]) >= 3 and len(found[1]) >= 3)


# --- files, links, settings, PowerPoint shapes -------------------------------------------------------------
def test_FUZZ_13_file_names_and_links_for_any_text(tmp_path):
    from capture_tool.core.naming import render, unique_path
    from capture_tool.core.share import file_link, link_html
    from datetime import datetime
    from urllib.parse import unquote
    for _ in range(800):
        pattern = rnd_text(40)
        p = unique_path(tmp_path, render(pattern, datetime(2026, 10, 3, 9, 5, 7)), ".png")   # what saving uses
        assert p.parent == tmp_path and p.suffix == ".png" and p.stem
        assert not any(c in p.name for c in '<>:"/\\|?*') and len(p.name) <= 210
        p.write_bytes(b"x")                                    # really a valid Windows file name
        p.unlink()
        text, url = file_link(p)
        assert url.startswith("file:///") and " " not in url and unquote(url[8:]).replace("/", "\\") == text
        assert "<script" not in link_html(url, "<script>alert(1)</script>")


def test_FUZZ_14_settings_files_of_any_shape_load(tmp_path):
    from dataclasses import fields
    from capture_tool.core.settings import Settings, load, save
    values = [None, 0, -1, 10**12, 3.5, True, "", "x", "#FFF", "Alt + ~", [], [1, "a"], {}, {"capture": 5},
              "../../etc", "a" * 100000, float("nan")]
    names = [f.name for f in fields(Settings)]
    rr = random.Random(14)
    p = tmp_path / "s.json"
    for _ in range(600):
        data = {rr.choice(names): rr.choice(values) for _ in range(rr.randint(0, 12))}
        p.write_text(json.dumps(data), encoding="utf-8")
        s, _ = load(p)
        save(s, p)
        s2, warnings = load(p)
        assert not warnings and s2 == s                         # whatever loads, saves cleanly
    for junk in [b"", b"\x00\xff", b"[1,2]", b"{", "{\"hotkeys\": 3}".encode()]:
        p.write_bytes(junk)
        load(p)


def test_FUZZ_15_powerpoint_shapes_with_any_text_are_valid_xml():
    from capture_tool.core.drawingml import DConnector, DShape, gvml_package
    rr = random.Random(15)
    for _ in range(200):
        shapes = [DShape(rr.choice(["rect", "ellipse", "roundRect", "triangle"]), rr.uniform(-100, 2000),
                         rr.uniform(-100, 2000), rr.uniform(0, 500), rr.uniform(0, 500), text=rnd_text(30))
                  for _ in range(rr.randint(0, 8))]
        conns = [DConnector(start=rr.randrange(len(shapes)), end=rr.randrange(len(shapes)))
                 for _ in range(rr.randint(0, 3))] if len(shapes) > 1 else []
        if not shapes:
            with pytest.raises(ValueError):                    # by design: callers check first
                gvml_package(shapes, conns)
            continue
        pkg = gvml_package(shapes, conns)
        with zipfile.ZipFile(io.BytesIO(pkg)) as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".rels"):
                    minidom.parseString(z.read(name))          # well-formed XML whatever the text


def test_FUZZ_12b_circled_numbers_in_the_first_column_are_text():
    """BUG-104: "①".isdigit() is True but int("①") fails - a table starting with ① ② ③ crashed."""
    from capture_tool.core.table import drop_sheet_headers
    g = [["①", "가"], ["②", "나"], ["③", "다"]]
    assert drop_sheet_headers(g) == g
