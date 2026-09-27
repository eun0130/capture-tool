"""Font list for the text tool: popular Korean fonts first (only those installed), then the rest."""
from __future__ import annotations

SEPARATOR = ("", "")

# (label shown to the user, family names this font can be installed under — English or Korean)
FAVORITES: list[tuple[str, list[str]]] = [
    ("맑은 고딕", ["Malgun Gothic", "맑은 고딕"]),
    ("나눔고딕", ["NanumGothic", "나눔고딕"]),
    ("나눔바른고딕", ["NanumBarunGothic", "나눔바른고딕"]),
    ("나눔스퀘어", ["NanumSquare", "나눔스퀘어"]),
    ("나눔명조", ["NanumMyeongjo", "나눔명조"]),
    ("본고딕 (Noto Sans KR)", ["Noto Sans KR", "Noto Sans CJK KR", "Source Han Sans KR"]),
    ("Pretendard", ["Pretendard"]),
    ("굴림", ["Gulim", "굴림"]),
    ("돋움", ["Dotum", "돋움"]),
    ("바탕", ["Batang", "바탕"]),
    ("궁서", ["Gungsuh", "궁서"]),
    ("함초롬바탕", ["HCR Batang", "함초롬바탕"]),
    ("함초롬돋움", ["HCR Dotum", "함초롬돋움"]),
    ("굴림체", ["GulimChe", "굴림체"]),
    ("돋움체", ["DotumChe", "돋움체"]),
    ("바탕체", ["BatangChe", "바탕체"]),
    ("궁서체", ["GungsuhChe", "궁서체"]),
]


def build_font_list(installed: list[str]) -> list[tuple[str, str]]:
    """[(label, family)] with installed favorites first, SEPARATOR, then the other fonts A→Z.
    Vertical-writing aliases ("@Font") and empty names are skipped."""
    fams = [f for f in dict.fromkeys(installed) if f and not f.startswith("@")]
    present = set(fams)
    head: list[tuple[str, str]] = []
    used: set[str] = set()
    for label, names in FAVORITES:
        fam = next((n for n in names if n in present), None)
        if fam is not None:
            head.append((label, fam))
            used.add(fam)
    rest = sorted((f for f in fams if f not in used), key=str.casefold)
    items = head[:]
    if head and rest:
        items.append(SEPARATOR)
    items += [(f, f) for f in rest]
    return items
