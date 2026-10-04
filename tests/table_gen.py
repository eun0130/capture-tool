"""Tables with known contents, generated for tests that the table readers work on tables never
seen during development (not tuned to the users' screenshots): terminal style (line characters,
monospace Korean, cell wrapping, dark/light, coloured words, arrows) and document style
(proportional font, full grid or separator lines only, wrapped cells)."""
import os
import random
import unicodedata

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

WORDS = ("요구사항 설계 코드 테스트 연결 추적성 매트릭스 수작업 관리 승인 반려 검토 결재 회의록 일정 담당자 "
         "고객 문서 자동화 배포 서버 로그 보안 권한 계정 데이터 분석 결과 보고서 화면 버튼 메뉴 설정 저장 "
         "불가 가능 필요 없음 있음 항상 가끔 매일 빠름 느림 정확 오류 경고 완료 진행 대기").split()
LATIN = "Excel Jira GitHub API PDF CI/CD git log URL branch commit PowerPoint Word KPI ERP".split()
JOSA = ["", "", "가", "를", "은", "에서", "로", "와"]


def words(rng, n):
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.7:
            out.append(rng.choice(WORDS) + rng.choice(JOSA))
        elif r < 0.85:
            out.append(rng.choice(LATIN))
        elif r < 0.93:
            out.append(str(rng.randint(1, 999)))
        else:
            out.append(rng.choice(["↔", "→"]))
    return " ".join(out)


def cw(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def wrap_cells(text, width):
    """Terminal-style wrap at character cells (breaks inside words)."""
    lines, cur, n = [], "", 0
    for ch in text:
        w = cw(ch)
        if n + w > width:
            lines.append(cur)
            cur, n = "", 0
            if ch == " ":
                continue
        cur += ch
        n += w
    if cur:
        lines.append(cur)
    return lines or [""]


def terminal(seed):
    rng = random.Random(seed)
    ncol = rng.randint(1, 4)
    size = rng.choice([13, 14, 16, 18, 20, 22])
    font = ImageFont.truetype("C:/Windows/Fonts/gulim.ttc", size, index=1)          # GulimChe (monospace)
    dark = rng.random() < 0.6
    bg, fg = ((30, 31, 31), (240, 240, 240)) if dark else ((255, 255, 255), (20, 20, 20))
    accent = (177, 185, 249) if dark else (120, 40, 200)
    widths = [rng.randint(6, 12) for _ in range(ncol)]
    widths[-1] = rng.randint(14, 34) if ncol > 1 else rng.randint(10, 30)
    nrow = rng.randint(3, 6)
    rows = [["항목", "설명", "비고", "상태"][:ncol] if ncol <= 4 else []]
    for r in range(nrow - 1):
        rows.append([words(rng, rng.randint(1, 3 if c < ncol - 1 else 7)) for c in range(ncol)])
    colored = {}
    for r in range(1, nrow):
        if rng.random() < 0.25:
            colored[(r, ncol - 1)] = True
    cell_w = max(8, round(size * 0.5))
    line_h = round(size * 1.6)
    total_w = sum(w + 3 for w in widths) + 1
    lines_per = [max(len(wrap_cells(c, w)) for c, w in zip(row, widths)) for row in rows]
    H = (sum(lines_per) + nrow + 1) * line_h + 10
    W = total_w * cell_w + 10
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    y = 5
    xs = [5]
    for w in widths:
        xs.append(xs[-1] + (w + 3) * cell_w)

    def rule(y):
        d.line([(xs[0] + cell_w // 2, y + line_h // 2), (xs[-1] - cell_w // 2, y + line_h // 2)], fill=fg, width=1)
        for x in xs:
            d.line([(x + cell_w // 2, y + line_h // 2), (x + cell_w // 2, y + line_h)], fill=fg, width=1)
    for r, row in enumerate(rows):
        rule(y)
        y += line_h
        wrapped = [wrap_cells(c, w) for c, w in zip(row, widths)]
        for k in range(lines_per[r]):
            for x in xs:
                d.line([(x + cell_w // 2, y), (x + cell_w // 2, y + line_h)], fill=fg, width=1)
            for c in range(ncol):
                if k < len(wrapped[c]):
                    col = accent if (r, c) in colored else fg
                    d.text((xs[c] + 2 * cell_w, y + (line_h - size) // 2), wrapped[c][k], font=font, fill=col)
            y += line_h
    rule(y)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), rows


def document(seed):
    rng = random.Random(500 + seed)
    ncol = rng.randint(2, 4)
    size = rng.choice([13, 14, 15, 16, 18])
    path = rng.choice(["C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/NanumGothic.ttf"])
    if not os.path.exists(path):                     # Nanum is not on every PC (or the build machine)
        path = "C:/Windows/Fonts/malgun.ttf"
    font = ImageFont.truetype(path, size)
    grid = rng.random() < 0.5                       # full grid, or separators only (Kakao-like)
    dark = rng.random() < 0.4
    bg, fg, line = ((30, 31, 31), (235, 235, 235), (110, 110, 110)) if dark else ((255, 255, 255), (25, 25, 25), (170, 170, 170))
    colw = [rng.randint(110, 260) for _ in range(ncol)]
    nrow = rng.randint(3, 6)
    rows = [["방식", "어떻게 작동하는지", "관계", "한계"][:ncol]]
    for r in range(nrow - 1):
        rows.append([words(rng, rng.randint(1, 2) if c == 0 else rng.randint(2, 8)) for c in range(ncol)])
    pad, lh = 10, round(size * 1.55)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    def wrap(text, w):
        out, cur = [], ""
        for ch in text:                              # Korean apps wrap at any character
            if probe.textlength(cur + ch, font=font) > w - 2 * pad:
                out.append(cur.rstrip())
                cur = "" if ch == " " else ch
            else:
                cur += ch
        if cur:
            out.append(cur)
        return out or [""]
    wrapped = [[wrap(c, w) for c, w in zip(row, colw)] for row in rows]
    heights = [max(len(x) for x in wr) * lh + 2 * pad for wr in wrapped]
    W, H = sum(colw) + 20, sum(heights) + 20
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    y = 10
    for r, wr in enumerate(wrapped):
        x = 10
        for c, w in enumerate(colw):
            for k, t in enumerate(wr[c]):
                d.text((x + pad, y + pad + k * lh), t, font=font, fill=fg)
            if grid:
                d.rectangle([x, y, x + w, y + heights[r]], outline=line)
            x += w
        if not grid:
            d.line([(10, y + heights[r]), (10 + sum(colw), y + heights[r])], fill=line, width=2)
        y += heights[r]
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), rows


def dist(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(got, truth):
    if got is None:
        return 0, 0.0, 0.0, 0.0
    shape = len(got) == len(truth) and all(len(g) == len(t) for g, t in zip(got, truth))
    cells = exact = sp = 0
    chars = errs = 0
    for r, trow in enumerate(truth):
        for c, t in enumerate(trow):
            g = got[r][c] if r < len(got) and c < len(got[r]) else ""
            cells += 1
            exact += g == t
            sp += g.replace(" ", "") == t.replace(" ", "")
            chars += max(1, len(t.replace(" ", "")))
            errs += dist(g.replace(" ", ""), t.replace(" ", ""))
    return int(shape), exact / cells, sp / cells, max(0.0, 1 - errs / chars)
