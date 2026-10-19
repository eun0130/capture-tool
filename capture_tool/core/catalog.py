"""The catalogue of saved captures behind 캡처 찾기: one sqlite file (FTS5, trigram tokenizer, so
Korean is found inside words) holding, per picture, what it looks like (hash, colours, kind of
content), where it came from (app, window title, capture kind, time), its tags (automatic and
the person's own) and its text - masked of personal data before it is stored. Qt-free; the file
path is injected (tests use a temp file)."""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .redact import mask
from .tagging import CaptureMeta, Described

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
SNIPPET = 100
FTS_MIN = 3                 # trigram index: shorter words are searched with LIKE
SIMILAR_DISTANCE = 16       # hamming distance of two 64-bit hashes still called "similar"
EMBED_BYTES = 1024          # 512 float16: a CLIP vector (core/shape.py); b"" = could not be embedded
MIN_CENTRE = 8              # nearest(centre=True) subtracts the pictures' mean once there are this many

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, folder TEXT NOT NULL, name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0, mtime REAL NOT NULL DEFAULT 0,
    w INTEGER, h INTEGER, kind TEXT, app TEXT, title TEXT, taken TEXT,
    phash INTEGER, colors TEXT, content TEXT, size_class TEXT,
    text TEXT NOT NULL DEFAULT '', text_done INTEGER NOT NULL DEFAULT 0,
    thumb BLOB, embed BLOB);
CREATE INDEX IF NOT EXISTS files_folder ON files(folder);
CREATE INDEX IF NOT EXISTS files_taken ON files(taken);
CREATE TABLE IF NOT EXISTS tags (file_id INTEGER NOT NULL, tag TEXT NOT NULL, source TEXT NOT NULL, ord INTEGER NOT NULL,
    PRIMARY KEY (file_id, tag, source));
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(body, tokenize="trigram");
"""


@dataclass(frozen=True)
class Hit:
    id: int
    path: str
    name: str
    folder: str
    taken: str
    kind: str
    app: str
    title: str
    content: str
    colors: tuple[str, ...]
    tags: tuple[str, ...]
    snippet: str
    phash: int
    text_done: int
    distance: int = -1          # similar(): hamming distance to the asked hash
    score: float = -1.0         # nearest(): cosine to the asked vector


def _signed(phash: int) -> int:
    return phash - (1 << 64) if phash >= (1 << 63) else phash


def _unsigned(v: int | None) -> int:
    v = v or 0
    return v + (1 << 64) if v < 0 else v


def _colors_text(colors: Iterable[str]) -> str:
    return "," + ",".join(colors) + "," if colors else ""


def _fts_query(words: list[str]) -> str:
    return " AND ".join('"' + w.replace('"', '""') + '"' for w in words)


def scan_folder(folder: str) -> list[tuple[str, int, float]]:
    """(path, size, mtime) of every picture file in the folder; [] when it can't be read."""
    out = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.name.lower().endswith(IMAGE_SUFFIXES) and e.is_file():
                    st = e.stat()
                    out.append((e.path, st.st_size, st.st_mtime))
    except OSError:
        return []
    return out


class Catalog:
    def __init__(self, db_path: Path | str):
        self.path = str(db_path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # --- writing ---------------------------------------------------------------------------------
    def add(self, path: str | Path, described: Described, meta: CaptureMeta, text: str | None = None,
            tags: Iterable[str] = (), thumb: bytes | None = None, size: int | None = None,
            mtime: float | None = None) -> int:
        """Insert or replace the picture at `path`. The person's own tags survive a replace.
        text=None: not read yet (the indexer reads it later)."""
        p = str(path)
        if size is None or mtime is None:
            try:
                st = os.stat(p)
                size, mtime = (st.st_size if size is None else size), (st.st_mtime if mtime is None else mtime)
            except OSError:
                size, mtime = size or 0, mtime or 0.0
        masked = mask(text) if text else ""
        with self._lock, self.db:
            row = self.db.execute("SELECT id FROM files WHERE path = ?", (p,)).fetchone()
            fid = row["id"] if row else None
            values = dict(path=p, folder=str(Path(p).parent), name=Path(p).name, size=size, mtime=mtime,
                          w=described.w, h=described.h, kind=meta.kind, app=meta.app, title=meta.title,
                          taken=meta.taken, phash=_signed(described.phash), colors=_colors_text(described.colors),
                          content=described.content, size_class=described.size_class, text=masked,
                          text_done=1 if text is not None else 0, thumb=thumb, embed=None)
            if fid is None:
                cols = ", ".join(values)
                fid = self.db.execute(f"INSERT INTO files ({cols}) VALUES ({', '.join(':' + c for c in values)})",
                                      values).lastrowid
            else:
                sets = ", ".join(f"{c} = :{c}" for c in values)
                values["id"] = fid
                self.db.execute(f"UPDATE files SET {sets} WHERE id = :id", values)
                self.db.execute("DELETE FROM tags WHERE file_id = ? AND source = 'auto'", (fid,))
            self._put_tags(fid, tags, "auto")
            self._reindex(fid)
        return int(fid)

    def set_file_stat(self, file_id: int, size: int, mtime: float) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE files SET size = ?, mtime = ? WHERE id = ?", (size, mtime, file_id))

    def set_text(self, file_id: int, text: str, extra_tags: Iterable[str] = ()) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE files SET text = ?, text_done = 1 WHERE id = ?", (mask(text or ""), file_id))
            self._put_tags(file_id, extra_tags, "auto")
            self._reindex(file_id)

    def mark_failed(self, file_id: int) -> None:
        with self._lock, self.db:
            self.db.execute("UPDATE files SET text_done = -1 WHERE id = ?", (file_id,))

    def set_embed(self, file_id: int, blob: bytes) -> None:
        """The picture's shape vector (b"" when it could not be made: it is not asked again)."""
        with self._lock, self.db:
            self.db.execute("UPDATE files SET embed = ? WHERE id = ?", (bytes(blob), file_id))

    def set_user_tags(self, file_id: int, tags: Iterable[str]) -> None:
        with self._lock, self.db:
            self.db.execute("DELETE FROM tags WHERE file_id = ? AND source = 'user'", (file_id,))
            self._put_tags(file_id, tags, "user")
            self._reindex(file_id)

    def remove(self, file_id: int) -> None:
        with self._lock, self.db:
            self._remove(file_id)

    def clear(self) -> None:
        with self._lock, self.db:
            self.db.execute("DELETE FROM tags")
            self.db.execute("DELETE FROM files")
            self.db.execute("DELETE FROM fts")

    def _remove(self, file_id: int) -> None:
        self.db.execute("DELETE FROM tags WHERE file_id = ?", (file_id,))
        self.db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        self.db.execute("DELETE FROM fts WHERE rowid = ?", (file_id,))

    def _put_tags(self, file_id: int, tags: Iterable[str], source: str) -> None:
        start = self.db.execute("SELECT COALESCE(MAX(ord), -1) FROM tags WHERE file_id = ? AND source = ?",
                                (file_id, source)).fetchone()[0] + 1
        seen = set()
        for i, t in enumerate(t.strip() for t in tags):
            if t and t not in seen:
                seen.add(t)
                self.db.execute("INSERT OR IGNORE INTO tags (file_id, tag, source, ord) VALUES (?, ?, ?, ?)",
                                (file_id, t, source, start + i))

    def _tags(self, file_id: int, source: str | None = None) -> list[str]:
        if source is None:
            rows = self.db.execute("SELECT tag FROM tags WHERE file_id = ? ORDER BY source = 'user', ord", (file_id,))
        else:
            rows = self.db.execute("SELECT tag FROM tags WHERE file_id = ? AND source = ? ORDER BY ord", (file_id, source))
        out, seen = [], set()
        for r in rows:
            if r["tag"] not in seen:
                seen.add(r["tag"])
                out.append(r["tag"])
        return out

    def _reindex(self, file_id: int) -> None:
        row = self.db.execute("SELECT name, app, title, text FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            return
        body = " ".join(part for part in (row["name"], row["app"] or "", row["title"] or "",
                                          " ".join(self._tags(file_id)), row["text"] or "") if part)
        self.db.execute("DELETE FROM fts WHERE rowid = ?", (file_id,))
        self.db.execute("INSERT INTO fts (rowid, body) VALUES (?, ?)", (file_id, body))

    # --- reading ---------------------------------------------------------------------------------
    def _hit(self, row, query_words: list[str] = (), distance: int = -1, score: float = -1.0) -> Hit:
        text = row["text"] or ""
        snippet = text[:SNIPPET]
        for w in query_words:
            i = text.lower().find(w.lower())
            if i >= 0:
                start = max(0, i - 30)
                snippet = ("…" if start else "") + text[start:start + SNIPPET]
                break
        colors = tuple(c for c in (row["colors"] or "").split(",") if c)
        return Hit(int(row["id"]), row["path"], row["name"], row["folder"], row["taken"] or "", row["kind"] or "",
                   row["app"] or "", row["title"] or "", row["content"] or "", colors, tuple(self._tags(row["id"])),
                   " ".join(snippet.split()), _unsigned(row["phash"]), int(row["text_done"]), distance, score)

    def get(self, file_id: int) -> Hit | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
            return self._hit(row) if row else None

    def count(self) -> int:
        with self._lock:
            return int(self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def pending_count(self) -> int:
        with self._lock:
            return int(self.db.execute("SELECT COUNT(*) FROM files WHERE text_done = 0").fetchone()[0])

    def pending(self, limit: int = 50) -> list[tuple[int, str]]:
        """Pictures whose text hasn't been read yet (oldest row first)."""
        with self._lock:
            rows = self.db.execute("SELECT id, path FROM files WHERE text_done = 0 ORDER BY id LIMIT ?", (limit,))
            return [(int(r["id"]), r["path"]) for r in rows]

    def pending_embed(self, limit: int = 50) -> list[tuple[int, str]]:
        """Pictures without a shape vector yet (oldest row first)."""
        with self._lock:
            rows = self.db.execute("SELECT id, path FROM files WHERE embed IS NULL ORDER BY id LIMIT ?", (limit,))
            return [(int(r["id"]), r["path"]) for r in rows]

    def embed_count(self) -> int:
        with self._lock:
            return int(self.db.execute("SELECT COUNT(*) FROM files WHERE length(embed) = ?", (EMBED_BYTES,)).fetchone()[0])

    def apps(self) -> list[str]:
        with self._lock:
            rows = self.db.execute("SELECT DISTINCT app FROM files WHERE app != '' ORDER BY app")
            return [r["app"] for r in rows]

    def thumb(self, file_id: int) -> bytes | None:
        with self._lock:
            row = self.db.execute("SELECT thumb FROM files WHERE id = ?", (file_id,)).fetchone()
            return bytes(row["thumb"]) if row and row["thumb"] else None

    def thumb_for(self, path: str | Path) -> bytes | None:
        with self._lock:
            row = self.db.execute("SELECT thumb FROM files WHERE path = ?", (str(path),)).fetchone()
            return bytes(row["thumb"]) if row and row["thumb"] else None

    def tags_of(self, file_id: int) -> dict[str, list[str]]:
        with self._lock:
            return {"auto": self._tags(file_id, "auto"), "user": self._tags(file_id, "user")}

    def search(self, query: str = "", kind: str | None = None, content: str | None = None, app: str | None = None,
               since: str | None = None, colour: str | None = None, folder: str | None = None,
               limit: int = 200) -> list[Hit]:
        """Every word of the query must occur (in the text, name, app, title or tags); the
        filters narrow further. No query: the newest first."""
        words = [w for w in (query or "").split() if w]
        long_words = [w for w in words if len(w) >= FTS_MIN]
        short_words = [w for w in words if len(w) < FTS_MIN]
        where, args = [], []
        joins = ""
        if long_words:
            joins = " JOIN fts ON fts.rowid = f.id"
            where.append("fts MATCH ?")
            args.append(_fts_query(long_words))
        elif short_words:
            joins = " JOIN fts ON fts.rowid = f.id"
        for w in short_words:
            where.append("fts.body LIKE ? ESCAPE '\\'")
            args.append("%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        w, a = self._filter_sql(kind, content, app, since, colour, folder)
        where += w
        args += a
        sql = "SELECT f.* FROM files f" + joins + (" WHERE " + " AND ".join(where) if where else "")
        sql += (" ORDER BY bm25(fts), f.taken DESC, f.id DESC" if long_words else " ORDER BY f.taken DESC, f.id DESC")
        sql += " LIMIT ?"
        args.append(limit)
        with self._lock:
            try:
                rows = self.db.execute(sql, args).fetchall()
            except sqlite3.OperationalError:
                return []
            return [self._hit(r, words) for r in rows]

    @staticmethod
    def _filter_sql(kind=None, content=None, app=None, since=None, colour=None, folder=None) -> tuple[list, list]:
        where, args = [], []
        for col, val in (("kind", kind), ("content", content), ("app", app), ("folder", folder)):
            if val:
                where.append(f"f.{col} = ?")
                args.append(val)
        if since:
            where.append("f.taken >= ?")
            args.append(since)
        if colour:
            where.append("f.colors LIKE ?")
            args.append(f"%,{colour},%")
        return where, args

    def nearest(self, vec, limit: int = 60, min_score: float = 0.0, kind: str | None = None,
                content: str | None = None, app: str | None = None, since: str | None = None,
                colour: str | None = None, folder: str | None = None, centre: bool = False) -> list[Hit]:
        """Pictures whose shape vector is closest to `vec` (cosine, best first), at least
        `min_score`, narrowed by the same filters as search(). Rows without a vector are skipped.
        centre=True (a phrase query): the pictures' mean is subtracted first, so no bland picture
        is close to everything."""
        q = np.asarray(vec, np.float32).reshape(-1)
        with self._lock:
            where, args = self._filter_sql(kind, content, app, since, colour, folder)
            where.append("length(f.embed) = ?")
            args.append(EMBED_BYTES)
            rows = self.db.execute("SELECT f.id, f.embed FROM files f WHERE " + " AND ".join(where), args).fetchall()
            if not rows:
                return []
            ids = np.fromiter((r["id"] for r in rows), np.int64, len(rows))
            mat = np.frombuffer(b"".join(bytes(r["embed"]) for r in rows), dtype=np.float16).reshape(len(rows), -1)
            mat = mat.astype(np.float32)
            if centre and len(rows) >= MIN_CENTRE:
                mat -= mat.mean(axis=0)
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                np.divide(mat, norms, out=mat, where=norms > 0)
            scores = mat @ q
            keep = np.flatnonzero(scores >= min_score)
            if keep.size == 0:
                return []
            top = keep[np.argsort(-scores[keep], kind="stable")][:limit]
            out = []
            for i in top:
                row = self.db.execute("SELECT * FROM files WHERE id = ?", (int(ids[i]),)).fetchone()
                if row:
                    out.append(self._hit(row, score=float(scores[i])))
            return out

    def similar(self, phash: int, limit: int = 50, max_distance: int = SIMILAR_DISTANCE) -> list[Hit]:
        """Pictures whose hash is within `max_distance` bits, nearest first."""
        with self._lock:
            rows = self.db.execute("SELECT id, phash FROM files").fetchall()
            scored = []
            for r in rows:
                d = bin(_unsigned(r["phash"]) ^ phash).count("1")
                if d <= max_distance:
                    scored.append((d, -int(r["id"])))
            scored.sort()
            out = []
            for d, neg in scored[:limit]:
                row = self.db.execute("SELECT * FROM files WHERE id = ?", (-neg,)).fetchone()
                if row:
                    out.append(self._hit(row, distance=d))
            return out

    # --- keeping up with the folder ---------------------------------------------------------------
    def reconcile(self, folder: str, entries: list[tuple[str, int, float]] | None = None
                  ) -> tuple[list[str], int, int]:
        """Compare the catalogue with the folder: pictures to (re)add, rows removed, rows moved
        (a renamed file keeps its size and time, so its row follows it)."""
        if entries is None:
            entries = scan_folder(folder)
        by_path = {p: (s, m) for p, s, m in entries}
        with self._lock, self.db:
            rows = self.db.execute("SELECT id, path, size, mtime FROM files WHERE folder = ?", (folder,)).fetchall()
            known = {r["path"]: r for r in rows}
            new, removed, moved = [], 0, 0
            gone = [r for r in rows if r["path"] not in by_path]
            fresh = [p for p in by_path if p not in known]
            by_stat: dict[tuple[int, int], str] = {}
            for p in fresh:
                s, m = by_path[p]
                by_stat.setdefault((s, int(m)), p)
            for r in gone:
                target = by_stat.pop((r["size"], int(r["mtime"])), None)
                if target is not None:
                    self.db.execute("UPDATE files SET path = ?, name = ? WHERE id = ?", (target, Path(target).name, r["id"]))
                    self._reindex(r["id"])
                    fresh.remove(target)
                    moved += 1
                else:
                    self._remove(r["id"])
                    removed += 1
            for p, r in known.items():
                if p in by_path:
                    s, m = by_path[p]
                    if s != r["size"] or int(m) != int(r["mtime"]):
                        self.db.execute("UPDATE files SET size = ?, mtime = ?, text_done = 0 WHERE id = ?", (s, m, r["id"]))
                        new.append(p)
            new += fresh
        return new, removed, moved
