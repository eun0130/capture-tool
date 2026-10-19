"""The catalogue of saved captures (sqlite + FTS5) behind 캡처 찾기: adding, searching by words,
filters, look-alikes, keeping up with the folder, user tags. Everything in a temp db."""
import os
from pathlib import Path

import pytest

from capture_tool.core.catalog import Catalog, Hit
from capture_tool.core.tagging import CaptureMeta, Described


def desc(phash=0x1234, colors=("흰색", "빨강"), content="text", w=400, h=300, size_class="piece"):
    return Described(w, h, phash, colors, content, size_class)


def meta(kind="area", app="", title="", taken="2026-10-20T09:00:00"):
    return CaptureMeta(kind, app, title, taken)


@pytest.fixture
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    yield c
    c.close()


def fill(cat, folder="D:/shots"):
    folder = str(Path(folder))
    a = cat.add(os.path.join(folder, "a.png"), desc(phash=0xF0F0, content="table"), meta("window", "excel", "매출현황 - Excel", "2026-10-18T10:00:00"),
                text="3분기 매출현황 보고서 010-1234-5678", tags=["창", "excel", "표", "흰색", "빨강", "매출현황"])
    b = cat.add(os.path.join(folder, "b.png"), desc(phash=0xF0F1, colors=("파랑",), content="code"), meta("area", "code", "main.py - Code", "2026-10-19T10:00:00"),
                text="def total(rows): return sum(r[1] for r in rows)", tags=["영역", "code", "코드", "파랑"])
    c = cat.add(os.path.join(folder, "c.jpg"), desc(phash=0x0F0F0F, colors=("초록",), content="photo"), meta("scroll", "chrome", "Sales Report", "2026-10-20T10:00:00"),
                text="Sales report Q3 — seoul office", tags=["스크롤", "chrome", "사진", "초록"])
    return a, b, c


def test_CAT_01_add_get_count_masked_text_and_thumb(cat):
    fid = cat.add("D:/shots/a.png", desc(), meta("window", "excel", "매출현황 - Excel"), text="연락처 010-1234-5678 매출",
                  tags=["창", "excel"], thumb=b"JPEGDATA", size=123, mtime=5.0)
    assert fid == 1 and cat.count() == 1
    hit = cat.get(fid)
    assert isinstance(hit, Hit) and hit.path == "D:/shots/a.png" and hit.name == "a.png" and hit.app == "excel"
    assert hit.kind == "window" and hit.content == "text" and hit.colors == ("흰색", "빨강") and hit.tags == ("창", "excel")
    assert "010-1234-5678" not in hit.snippet and "***" in hit.snippet and "매출" in hit.snippet
    assert cat.thumb(fid) == b"JPEGDATA" and cat.thumb_for("D:/shots/a.png") == b"JPEGDATA" and cat.thumb_for("x") is None
    assert cat.get(99) is None
    assert cat.search("1234") == []                               # the number never went in


def test_CAT_02_search_by_words(cat):
    a, b, c = fill(cat)
    assert [h.id for h in cat.search("")] == [c, b, a]                   # newest first
    assert [h.id for h in cat.search("출현황")] == [a]                   # 3+ letters: FTS trigram (inside a word)
    assert [h.id for h in cat.search("매출")] == [a]                     # 2 letters: LIKE
    assert [h.id for h in cat.search("SALES")] == [c]                    # case does not matter
    assert [h.id for h in cat.search("sales seoul")] == [c]              # every word must match
    assert cat.search("sales 매출") == []
    assert [h.id for h in cat.search("excel")] == [a]                    # app / tags / title are searched too
    assert [h.id for h in cat.search("Code")] == [b]
    assert [h.id for h in cat.search("main.py")] == [b]                  # punctuation in the query is fine
    assert cat.search('"quoted" (x)') == []
    hit = cat.search("seoul")[0]
    assert "seoul" in hit.snippet.lower() and len(hit.snippet) <= 120


def test_CAT_03_filters(cat):
    a, b, c = fill(cat)
    assert [h.id for h in cat.search(kind="window")] == [a]
    assert [h.id for h in cat.search(content="code")] == [b]
    assert [h.id for h in cat.search(app="chrome")] == [c]
    assert [h.id for h in cat.search(colour="파랑")] == [b]
    assert [h.id for h in cat.search(since="2026-10-19")] == [c, b]
    assert [h.id for h in cat.search("sales", content="photo")] == [c] and cat.search("sales", content="code") == []
    assert sorted(cat.apps()) == ["chrome", "code", "excel"]
    assert [h.id for h in cat.search(limit=1)] == [c]


def test_CAT_04_similar_pictures_by_hash_distance(cat):
    a, b, c = fill(cat)
    hits = cat.similar(0xF0F0)
    assert [h.id for h in hits] == [a, b]                                # a: distance 0, b: 1; c: 20 away = out
    assert hits[0].distance == 0 and hits[1].distance == 1
    assert [h.id for h in cat.similar(0x0F0F0F, max_distance=16)] == [c]
    assert [h.id for h in cat.similar(0x0F0F0F, max_distance=64)] == [c, b, a]
    big = cat.add("D:/shots/big.png", desc(phash=2 ** 64 - 1), meta())
    assert cat.get(big).phash == 2 ** 64 - 1 and cat.similar(2 ** 64 - 1)[0].id == big


def test_CAT_05_reconcile_follows_the_folder(cat, tmp_path):
    folder = tmp_path / "shots"
    folder.mkdir()
    for name in ("a.png", "b.png", "c.jpg"):
        (folder / name).write_bytes(b"x" * (10 + len(name)))
    sizes = {n: (folder / n).stat().st_size for n in ("a.png", "b.png", "c.jpg")}
    mtimes = {n: (folder / n).stat().st_mtime for n in ("a.png", "b.png", "c.jpg")}
    a, b, c = fill(cat, str(folder))
    for n, fid in zip(("a.png", "b.png", "c.jpg"), (a, b, c)):
        cat.set_file_stat(fid, sizes[n], mtimes[n])
    new, removed, moved = cat.reconcile(str(folder))
    assert (new, removed, moved) == ([], 0, 0)
    (folder / "b.png").rename(folder / "renamed.png")                   # same size and mtime: a move
    (folder / "c.jpg").unlink()
    (folder / "d.png").write_bytes(b"new picture")
    (folder / "a.png").write_bytes(b"changed a lot more bytes")        # changed: described again
    new, removed, moved = cat.reconcile(str(folder))
    assert sorted(Path(p).name for p in new) == ["a.png", "d.png"] and removed == 1 and moved == 1
    assert cat.get(b).path == str(folder / "renamed.png") and cat.get(b).name == "renamed.png"
    assert cat.get(c) is None and cat.count() == 2
    assert cat.search("def total")[0].id == b                           # the moved row kept its text
    d = cat.add(str(folder / "d.png"), desc(), meta())
    assert cat.get(a).text_done == 0 and cat.pending() == [(a, str(folder / "a.png")), (d, str(folder / "d.png"))]


def test_CAT_06_user_tags_are_searchable_and_kept_apart(cat):
    a, b, c = fill(cat)
    cat.set_user_tags(a, ["중요", "3분기", "excel"])
    assert cat.tags_of(a) == {"auto": ["창", "excel", "표", "흰색", "빨강", "매출현황"], "user": ["중요", "3분기", "excel"]}
    assert [h.id for h in cat.search("중요")] == [a]
    assert cat.get(a).tags == ("창", "excel", "표", "흰색", "빨강", "매출현황", "중요", "3분기")
    cat.set_user_tags(a, ["보고"])
    assert cat.tags_of(a)["user"] == ["보고"] and cat.search("중요") == [] and cat.search("보고")[0].id == a
    cat.add(os.path.join(str(Path("D:/shots")), "a.png"), desc(content="ui"), meta("window", "excel"), text="새 글", tags=["창", "excel", "화면"])
    assert cat.count() == 3 and cat.tags_of(a)["user"] == ["보고"] and cat.get(a).content == "ui"   # re-added: user tags stay


def test_CAT_07_text_comes_later_for_the_backlog(cat):
    fid = cat.add("D:/shots/later.png", desc(), meta(), text=None, tags=["영역"])
    assert cat.pending() == [(fid, "D:/shots/later.png")] and cat.get(fid).text_done == 0
    assert cat.search("later")[0].id == fid                             # the name is searchable at once
    cat.set_text(fid, "읽은 글 010-9999-8888", ["읽은"])
    assert cat.pending() == [] and cat.get(fid).text_done == 1
    assert cat.search("읽은 글")[0].id == fid and "8888" not in cat.get(fid).snippet and "읽은" in cat.get(fid).tags
    other = cat.add("D:/shots/bad.png", desc(), meta())
    cat.mark_failed(other)
    assert cat.pending() == [] and cat.get(other).text_done == -1
    assert cat.pending_count() == 0


def test_CAT_08_remove_and_clear(cat):
    a, b, c = fill(cat)
    cat.remove(b)
    assert cat.count() == 2 and cat.search("total") == [] and cat.get(b) is None
    cat.clear()
    assert cat.count() == 0 and cat.search("") == [] and cat.apps() == []


def test_CAT_09_reopening_keeps_everything(tmp_path):
    db = tmp_path / "catalog.db"
    c1 = Catalog(db)
    fill(c1)
    c1.close()
    c2 = Catalog(db)
    assert c2.count() == 3 and [h.id for h in c2.search("출현황")] == [1]
    c2.close()


def test_CAT_10_bad_folder_scan_is_empty_not_an_error(cat, tmp_path):
    assert cat.reconcile(str(tmp_path / "missing")) == ([], 0, 0)
    assert cat.search("x") == [] and cat.similar(1) == []


def vec(i: int):
    import numpy as np
    v = np.zeros(512, np.float32)
    v[i] = 1.0
    return v


def test_CAT_11_embeddings_are_stored_later_and_pending_until_then(cat):
    from capture_tool.core.shape import to_blob
    a, b, c = fill(cat)
    assert cat.embed_count() == 0 and [i for i, _ in cat.pending_embed()] == [a, b, c]
    cat.set_embed(a, to_blob(vec(0)))
    cat.set_embed(b, b"")                                            # could not be embedded: never asked again
    assert cat.embed_count() == 1 and [i for i, _ in cat.pending_embed()] == [c]
    assert cat.pending_embed(limit=0) == []
    cat.add(os.path.join(str(Path("D:/shots")), "a.png"), desc(), meta("area"))  # re-added (changed on disk): embed again
    assert [i for i, _ in cat.pending_embed()] == [a, c]
    cat.set_embed(c, to_blob(vec(1)))
    cat.remove(c)
    assert cat.embed_count() == 0 and cat.pending_embed() == [(a, os.path.join(str(Path("D:/shots")), "a.png"))]


def test_CAT_12_nearest_by_cosine_with_filters_and_a_floor(cat):
    import numpy as np
    from capture_tool.core.shape import to_blob
    a, b, c = fill(cat)
    cat.set_embed(a, to_blob(vec(0)))
    cat.set_embed(b, to_blob(vec(1)))
    q = np.zeros(512, np.float32)
    q[0], q[1] = 0.8, 0.6                                            # closer to a than to b; c has no vector
    hits = cat.nearest(q)
    assert [h.id for h in hits] == [a, b] and abs(hits[0].score - 0.8) < 1e-3 and abs(hits[1].score - 0.6) < 1e-3
    assert cat.nearest(q, min_score=0.7) == hits[:1] and cat.nearest(q, limit=1) == hits[:1]
    assert [h.id for h in cat.nearest(q, content="code")] == [b]
    assert [h.id for h in cat.nearest(q, since="2026-10-19")] == [b]
    assert [h.id for h in cat.nearest(q, colour="빨강")] == [a]
    assert cat.nearest(q, app="chrome") == [] and cat.nearest(q, kind="window", content="code") == []
    assert Hit.__dataclass_fields__["score"].default == -1.0 and cat.search("")[0].score == -1.0
    cat.set_embed(a, b"")
    assert [h.id for h in cat.nearest(q)] == [b]                        # a failed blob is skipped


def test_CAT_13_centred_nearest_takes_the_bland_hub_out(cat):
    import numpy as np
    from capture_tool.core.shape import to_blob
    common = np.zeros(512, np.float32)
    common[0] = 1.0                                                     # what every screenshot shares
    ids = []
    for i in range(10):
        own = np.zeros(512, np.float32)
        own[10 + i] = 1.0
        v = common + 0.5 * own                                          # each picture: the common part + its own
        if i == 0:
            v = common                                                  # the hub: nothing but the common part
        ids.append(cat.add(f"D:/s/{i}.png", desc(), meta()))
        cat.set_embed(ids[-1], to_blob(v / np.linalg.norm(v)))
    q = 0.2 * common + np.eye(512, dtype=np.float32)[13]                # a (centred) phrase about picture 3
    q /= np.linalg.norm(q)
    raw = cat.nearest(q, min_score=0.08)
    assert raw[0].id == ids[3] and ids[0] in [h.id for h in raw]        # raw: the hub still shows up
    hits = cat.nearest(q, centre=True, min_score=0.08)
    assert hits[0].id == ids[3] and hits[0].score > 0.9 and ids[0] not in [h.id for h in hits]
    low = cat.nearest(q, centre=True, min_score=-1.0)
    assert low[-1].id == ids[0] and low[-1].score < 0 and len(low) == 10
    assert cat.nearest(q, centre=True, limit=2)[0].id == ids[3]
    for fid in ids[3:]:
        cat.remove(fid)
    assert cat.nearest(q, centre=True, min_score=0.08)[0].id == ids[0]   # fewer than 8 pictures: raw again, hub first
