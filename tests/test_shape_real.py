"""The real shape-search pack (skipped unless it is installed on this PC): Korean and English
phrases rank the matching synthetic picture first, and the timings are recorded."""
import time

import cv2
import numpy as np
import pytest

from capture_tool.core import shape
from capture_tool.core.catalog import Catalog
from capture_tool.core.tagging import CaptureMeta, Described

pytestmark = pytest.mark.skipif(shape.find_clip() is None, reason="shape pack not installed")


def table_pic():
    img = np.full((400, 600, 3), 255, np.uint8)
    for y in range(40, 400, 40):
        cv2.line(img, (20, y), (580, y), (0, 0, 0), 1)
    for x in range(20, 600, 140):
        cv2.line(img, (x, 40), (x, 360), (0, 0, 0), 1)
    for r in range(8):
        for c in range(4):
            cv2.putText(img, f"{r * 7 + c}", (30 + c * 140, 70 + r * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    return img


def code_pic():
    img = np.full((400, 600, 3), 30, np.uint8)
    for i, l in enumerate(["def total(rows):", "    s = 0", "    for r in rows:", "        s += r[1]", "    return s"]):
        cv2.putText(img, l, (20, 40 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 220, 120), 2)
    return img


def chart_pic():
    img = np.full((400, 600, 3), 255, np.uint8)
    for i, h in enumerate([120, 200, 260, 180, 300]):
        cv2.rectangle(img, (60 + i * 100, 360 - h), (120 + i * 100, 360), (200, 80, 30), -1)
    cv2.line(img, (40, 360), (580, 360), (0, 0, 0), 2)
    cv2.line(img, (40, 360), (40, 40), (0, 0, 0), 2)
    return img


def dialog_pic():
    img = np.full((400, 600, 3), 240, np.uint8)
    cv2.rectangle(img, (100, 100), (500, 300), (255, 255, 255), -1)
    cv2.rectangle(img, (100, 100), (500, 300), (120, 120, 120), 2)
    cv2.putText(img, "Save changes?", (150, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    cv2.rectangle(img, (280, 230), (380, 270), (60, 120, 220), -1)
    cv2.putText(img, "OK", (310, 258), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.rectangle(img, (390, 230), (490, 270), (200, 200, 200), -1)
    cv2.putText(img, "Cancel", (400, 258), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    return img


PICS = {"table": table_pic, "code": code_pic, "chart": chart_pic, "dialog": dialog_pic}
QUERIES = [("막대 그래프", "chart"), ("확인 취소 버튼이 있는 대화 상자", "dialog"), ("검은 바탕의 소스 코드", "code"),
           ("a spreadsheet table with numbers", "table"), ("a bar chart", "chart"), ("source code", "code")]


def test_SHR_01_phrases_rank_the_matching_picture_first_and_fast(tmp_path):
    s = shape.ShapeSearch()
    t0 = time.perf_counter()
    s.text_vector("warm")
    load_ms = (time.perf_counter() - t0) * 1000
    cat = Catalog(tmp_path / "catalog.db")
    embed_ms = []
    for name, make in PICS.items():
        img = make()
        fid = cat.add(tmp_path / f"{name}.png", Described(600, 400, 0, (), "ui", "piece"), CaptureMeta("area"))
        t0 = time.perf_counter()
        cat.set_embed(fid, s.image_blob(img))
        embed_ms.append((time.perf_counter() - t0) * 1000)
    big = cv2.resize(table_pic(), (3840, 2160))
    t0 = time.perf_counter()
    s.image_blob(big)
    big_ms = (time.perf_counter() - t0) * 1000
    wrong = []
    text_ms = []
    for words, expect in QUERIES:
        t0 = time.perf_counter()
        vec = s.text_vector(words)
        text_ms.append((time.perf_counter() - t0) * 1000)
        hits = cat.nearest(vec, min_score=-1.0, centre=True)        # 4 pictures: ranking is what matters here
        if not hits or hits[0].name != f"{expect}.png":
            wrong.append((words, [(h.name, round(h.score, 3)) for h in hits]))
    print(f"\nshape pack: load {load_ms:.0f} ms, embed 600x400 {max(embed_ms):.0f} ms, 4K {big_ms:.0f} ms, "
          f"text {max(text_ms):.1f} ms")
    assert wrong == []
    assert big_ms < 400 and max(text_ms) < 100
    same = s.image_vector(table_pic())
    assert cat.nearest(same, min_score=shape.SAME_SCORE)[0].name == "table.png"      # picture -> picture
    assert cat.nearest(s.image_vector(dialog_pic()), min_score=shape.SAME_SCORE)[0].name == "dialog.png"
    cat.close()
