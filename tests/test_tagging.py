"""Automatic tags for a saved capture: what it looks like (hash, colours, kind of content) and
what its text is about - all computed on the PC, no model needed."""
import cv2
import numpy as np

from capture_tool.core import tagging as tg
from capture_tool.core.ocr import OcrLine


def _canvas(w=400, h=300, color=(255, 255, 255)):
    return np.full((h, w, 3), color, np.uint8)


def _line(text, x=10, y=10, w=200, h=20):
    return OcrLine(text, (x, y, w, h), 0.95)


def _text_picture(texts, w=400):
    img = _canvas(w, 40 + 30 * len(texts))
    lines = []
    for i, t in enumerate(texts):
        y = 20 + 30 * i
        cv2.putText(img, "x" * min(len(t), 30), (10, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        lines.append(_line(t, 10, y, min(len(t), 30) * 12, 22))
    return img, lines


def test_TAG_01_phash_tells_the_same_picture_from_a_different_one():
    rng = np.random.default_rng(1)
    a = _canvas()
    cv2.rectangle(a, (40, 40), (200, 160), (30, 60, 200), -1)
    cv2.circle(a, (300, 200), 50, (0, 0, 0), -1)
    cv2.putText(a, "Sales Q3", (60, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    assert tg.phash(a) == tg.phash(a.copy()) and tg.hamming(tg.phash(a), tg.phash(a)) == 0
    shifted = np.roll(a, 2, axis=1)
    assert tg.hamming(tg.phash(a), tg.phash(shifted)) <= 10
    smaller = cv2.resize(a, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    assert tg.hamming(tg.phash(a), tg.phash(smaller)) <= 10
    jpeg = cv2.imdecode(cv2.imencode(".jpg", a, [cv2.IMWRITE_JPEG_QUALITY, 70])[1], cv2.IMREAD_COLOR)
    assert tg.hamming(tg.phash(a), tg.phash(jpeg)) <= 6
    other = rng.integers(0, 255, a.shape, np.uint8)
    assert tg.hamming(tg.phash(a), tg.phash(other)) > 20
    b = _canvas()
    cv2.rectangle(b, (220, 100), (380, 280), (30, 60, 200), -1)
    assert tg.hamming(tg.phash(a), tg.phash(b)) > 12
    assert 0 <= tg.phash(a) < 2 ** 64


def test_TAG_02_colour_names_by_share():
    img = _canvas(300, 200)
    cv2.rectangle(img, (0, 0), (180, 130), (40, 40, 220), -1)      # BGR red: 39%
    cv2.rectangle(img, (200, 140), (300, 200), (220, 60, 40), -1)  # blue: 10%
    assert tg.colour_names(img) == ["흰색", "빨강", "파랑"]
    dark = _canvas(100, 100, (20, 20, 20))
    assert tg.colour_names(dark) == ["검정"]
    green = _canvas(100, 100, (60, 180, 60))
    assert tg.colour_names(green)[0] == "초록"
    assert tg.colour_names(np.zeros((0, 0, 3), np.uint8)) == []


def test_TAG_03_content_kind_photo_table_code_text_ui():
    rng = np.random.default_rng(2)
    photo = np.clip(rng.normal(120, 40, (300, 400, 3)), 0, 255).astype(np.uint8)
    assert tg.content_kind(photo, None) == "photo"
    table = _canvas()
    for y in (40, 100, 160, 220):
        cv2.line(table, (20, y), (380, y), (0, 0, 0), 2)
    for x in (20, 150, 280, 380):
        cv2.line(table, (x, 40), (x, 220), (0, 0, 0), 2)
    assert tg.content_kind(table, [_line("이름", 30, 50), _line("값", 160, 50)]) == "table"
    code_img, code_lines = _text_picture(["def total(rows):", "    s = 0", "    for r in rows:", "        s += r[1]",
                                          "    return s", "print(total(data))"])
    assert tg.content_kind(code_img, code_lines) == "code"
    text_img, text_lines = _text_picture(["매출 현황 보고서", "3분기 매출은 지난해보다 12% 늘었습니다.",
                                          "주요 원인은 신제품 출시와 해외 판매 증가입니다.", "4분기 전망도 밝습니다."])
    assert tg.content_kind(text_img, text_lines) == "text"
    ui = _canvas()
    cv2.rectangle(ui, (150, 130), (250, 170), (200, 120, 60), -1)
    assert tg.content_kind(ui, [_line("확인", 180, 140, 40, 20)]) == "ui"
    assert tg.content_kind(ui, None) == "ui"


def test_TAG_04_size_class():
    assert tg.size_class(3840, 2160, (3840, 2160)) == "full"
    assert tg.size_class(3500, 2000, (3840, 2160)) == "full"
    assert tg.size_class(1200, 800, (3840, 2160)) == "window"
    assert tg.size_class(300, 120, (3840, 2160)) == "piece"
    assert tg.size_class(1920, 1080) == "full" and tg.size_class(640, 400) == "window" and tg.size_class(100, 80) == "piece"


def test_TAG_05_keywords_count_words_without_particles_numbers_or_single_letters():
    lines = [_line("매출 현황 보고서"), _line("매출은 2026년 3분기에 12% 늘었다"), _line("보고서 작성: 홍길동"),
             _line("매출 증가 a b"), _line("Sales report sales")]
    assert tg.keywords(lines, 4) == ["매출", "보고서", "sales", "현황"]
    assert tg.keywords([], 5) == [] and tg.keywords(None, 5) == []
    assert tg.keywords([_line("x 1 22 ,, --")], 5) == []


def test_TAG_06_describe_and_auto_tags():
    img, lines = _text_picture(["매출 현황 보고서", "3분기 매출은 지난해보다 12% 늘었습니다.",
                                "주요 원인은 신제품 출시와 해외 판매 증가입니다."])
    d = tg.describe(img, lines, screen=(1920, 1080))
    assert (d.w, d.h) == (img.shape[1], img.shape[0]) and d.content == "text" and d.size_class == "piece"
    assert d.colors[0] == "흰색" and 0 <= d.phash < 2 ** 64
    meta = tg.CaptureMeta(kind="window", app="excel", title="매출현황 - Excel", taken="2026-10-20T09:30:00")
    tags = tg.auto_tags(meta, d, lines)
    assert tags[:3] == ["창", "excel", "글"]
    assert "흰색" in tags and "매출" in tags and "매출현황" in tags and "Excel" not in tags   # title words, app once
    assert len(tags) == len(set(tags))
    assert tg.auto_tags(tg.CaptureMeta(), d, None)[:2] == ["영역", "글"]
    thumb = tg.thumbnail(img)
    small = cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR)
    assert small.shape[1] <= tg.THUMB_W and small.shape[0] <= tg.THUMB_H and len(thumb) < 30_000
