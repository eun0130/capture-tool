"""Address book for sending captures by mail. One per Windows user (it lives in that user's
app-data folder), encrypted on disk (DPAPI via the caller's protect/unprotect), never uploaded
and never written to the log. Groups, recent and frequent lists; CSV import/export for moving
it from Gmail / Naver / Excel."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_CONTACTS = 2000
MAX_GROUPS = 100
MAX_RECENT = 20
MAX_EMAIL = 254


class InvalidEmail(ValueError):
    pass


class BookFull(Exception):
    pass


class SecretError(Exception):
    pass


_LOCAL = re.compile(r"[^\s@,;<>()\[\]\\\"]{1,64}")
_LABEL = re.compile(r"[^\W_](?:[\w-]{0,61}[^\W_])?", re.UNICODE)


def normalize_email(raw: str) -> str:
    """'이영희 <Lee@Corp.COM>' / 'mailto:x@y' -> 'Lee@corp.com'; anything else that isn't one
    plain address raises InvalidEmail."""
    if not isinstance(raw, str) or any(ch in raw for ch in "\r\n\t"):
        raise InvalidEmail(raw)
    s = raw.strip()
    m = re.fullmatch(r".*<([^<>]+)>", s)
    if m:
        s = m.group(1).strip()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    if not s or len(s) > MAX_EMAIL or s.count("@") != 1:
        raise InvalidEmail(raw)
    local, domain = s.split("@")
    labels = domain.split(".")
    if not _LOCAL.fullmatch(local) or len(labels) < 2 or not all(_LABEL.fullmatch(l) for l in labels):
        raise InvalidEmail(raw)
    return f"{local}@{domain.lower()}"


def is_email(raw: str) -> bool:
    try:
        normalize_email(raw)
        return True
    except InvalidEmail:
        return False


@dataclass
class Contact:
    name: str
    email: str


@dataclass
class Group:
    name: str
    members: list[str] = field(default_factory=list)


class AddressBook:
    def __init__(self):
        self.contacts: list[Contact] = []
        self.groups: list[Group] = []
        self.recent: list[str] = []
        self.uses: dict[str, int] = {}

    # --- contacts ------------------------------------------------------------------------------
    def get(self, email: str) -> Contact | None:
        key = email.lower()
        return next((c for c in self.contacts if c.email.lower() == key), None)

    def add(self, name: str, email: str) -> Contact:
        email = normalize_email(email)
        name = (name or "").strip()[:100] or email
        old = self.get(email)
        if old is not None:
            old.name = name
            return old
        if len(self.contacts) >= MAX_CONTACTS:
            raise BookFull(f"주소는 {MAX_CONTACTS}개까지 저장할 수 있습니다.")
        c = Contact(name, email)
        self.contacts.append(c)
        return c

    def remove(self, email: str) -> None:
        key = email.lower()
        self.contacts = [c for c in self.contacts if c.email.lower() != key]
        for g in self.groups:
            g.members = [m for m in g.members if m.lower() != key]
        self.recent = [r for r in self.recent if r.lower() != key]
        self.uses.pop(key, None)

    def search(self, q: str) -> list[Contact]:
        q = (q or "").strip().lower()
        return [c for c in self.contacts if not q or q in c.name.lower() or q in c.email.lower()]

    # --- groups --------------------------------------------------------------------------------
    def group(self, name: str) -> Group | None:
        return next((g for g in self.groups if g.name == name), None)

    def add_group(self, name: str, members: list[str]) -> Group:
        name = (name or "").strip()[:60]
        if not name:
            raise ValueError("그룹 이름을 넣어 주세요.")
        good = []
        for m in members:
            try:
                e = normalize_email(m)
            except InvalidEmail:
                continue
            if e.lower() not in (x.lower() for x in good):
                good.append(e)
        g = self.group(name)
        if g is None:
            if len(self.groups) >= MAX_GROUPS:
                raise BookFull(f"그룹은 {MAX_GROUPS}개까지 만들 수 있습니다.")
            g = Group(name)
            self.groups.append(g)
        g.members = good
        return g

    def remove_group(self, name: str) -> None:
        self.groups = [g for g in self.groups if g.name != name]

    # --- choosing recipients ------------------------------------------------------------------------
    def _expand(self, entries: list[str]) -> list[str]:
        out: list[str] = []
        for e in entries:
            if e.startswith("group:"):
                g = self.group(e[6:])
                out.extend(g.members if g else [])
            else:
                try:
                    out.append(normalize_email(e))
                except InvalidEmail:
                    continue
        return out

    def resolve(self, to: list[str], cc: list[str]) -> tuple[list[str], list[str]]:
        """Groups expanded; each address once; someone in both To and Cc stays in To."""
        seen: set[str] = set()
        out_to, out_cc = [], []
        for src, dst in ((to, out_to), (cc, out_cc)):
            for e in self._expand(src):
                if e.lower() not in seen:
                    seen.add(e.lower())
                    dst.append(e)
        return out_to, out_cc

    def mark_used(self, emails: list[str]) -> None:
        for e in emails:
            k = e.lower()
            self.uses[k] = self.uses.get(k, 0) + 1
            self.recent = [r for r in self.recent if r.lower() != k]
            self.recent.insert(0, e)
        del self.recent[MAX_RECENT:]

    def frequent(self, n: int = 8) -> list[Contact]:
        used = sorted((c for c in self.contacts if self.uses.get(c.email.lower())),
                      key=lambda c: -self.uses[c.email.lower()])
        rest = [c for c in self.contacts if c not in used]
        return (used + rest)[:n]

    # --- (de)serialisation ------------------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({"contacts": [{"name": c.name, "email": c.email} for c in self.contacts],
                           "groups": [{"name": g.name, "members": g.members} for g in self.groups],
                           "recent": self.recent, "uses": self.uses}, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "AddressBook":
        b = cls()
        data = json.loads(text)
        if not isinstance(data, dict):
            return b
        for c in data.get("contacts") or []:
            if isinstance(c, dict) and isinstance(c.get("email"), str):
                try:
                    b.add(c.get("name") if isinstance(c.get("name"), str) else "", c["email"])
                except (InvalidEmail, BookFull):
                    continue
        for g in data.get("groups") or []:
            if isinstance(g, dict) and isinstance(g.get("name"), str) and isinstance(g.get("members"), list):
                try:
                    b.add_group(g["name"], [m for m in g["members"] if isinstance(m, str)])
                except (ValueError, BookFull):
                    continue
        b.recent = [r for r in (data.get("recent") or []) if isinstance(r, str) and is_email(r)][:MAX_RECENT]
        uses = data.get("uses") if isinstance(data.get("uses"), dict) else {}
        b.uses = {k: v for k, v in uses.items() if isinstance(k, str) and isinstance(v, int) and v > 0}
        return b


# --- storage -------------------------------------------------------------------------------------------
def save(book: AddressBook, path, protect) -> None:
    """Encrypt and write atomically: a failure leaves the previous file as it was."""
    path = Path(path)
    blob = protect(book.to_json())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"v": 1, "data": blob}), encoding="utf-8")
    os.replace(tmp, path)


def load(path, unprotect) -> tuple[AddressBook, str]:
    """(book, warning). A file that can't be read (another Windows user's, a broken one) is
    moved aside - never deleted - and an empty book is returned with a warning."""
    path = Path(path)
    if not path.exists():
        return AddressBook(), ""
    try:
        outer = json.loads(path.read_text(encoding="utf-8"))
        return AddressBook.from_json(unprotect(outer["data"])), ""
    except Exception:  # noqa: BLE001 - any failure means: keep the file, start fresh
        kept = path.with_name(f"{path.stem}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
        try:
            os.replace(path, kept)
        except OSError:
            pass
        return AddressBook(), (f"주소록을 읽지 못해 새로 시작합니다. 예전 파일은 {kept.name}로 남겨 두었습니다. "
                               "(다른 Windows 사용자의 파일이거나 손상된 파일)")


# --- CSV -------------------------------------------------------------------------------------------------
_NAME_HEADERS = ("name", "이름", "성명", "담당자", "display name", "full name", "표시 이름")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def import_csv(data: bytes) -> tuple[list[Contact], list[str]]:
    """Contacts from a CSV exported by Gmail / Naver / Excel (UTF-8 or cp949). Returns
    (contacts, skipped rows as short reasons). Rows without any address are ignored."""
    found: list[Contact] = []
    skipped: list[str] = []
    try:
        rows = list(csv.reader(io.StringIO(_decode(data))))
    except (csv.Error, ValueError):
        return [], []
    if not rows:
        return [], []
    head = [h.strip().lower() for h in rows[0]]
    mail_cols = [i for i, h in enumerate(head) if ("mail" in h or "메일" in h) and "type" not in h and "유형" not in h]
    name_col = next((i for i, h in enumerate(head) if h in _NAME_HEADERS), None)
    given = next((i for i, h in enumerate(head) if h in ("given name", "first name")), None)
    family = next((i for i, h in enumerate(head) if h in ("family name", "last name")), None)
    seen: set[str] = set()
    for n, row in enumerate(rows[1:], start=2):
        cells = [c.strip() for c in row]
        if mail_cols:
            values = [cells[i] for i in mail_cols if i < len(cells) and cells[i]]
        else:
            values = [c for c in cells if "@" in c]
        if not values:
            continue
        name = cells[name_col] if name_col is not None and name_col < len(cells) else ""
        if not name and given is not None:
            name = " ".join(x for x in (cells[family] if family is not None and family < len(cells) else "",
                                         cells[given] if given < len(cells) else "") if x)
        good = False
        for v in values:
            try:
                e = normalize_email(v)
            except InvalidEmail:
                continue
            good = True
            if e.lower() in seen:
                continue
            seen.add(e.lower())
            found.append(Contact(name.lstrip("'") or e, e))
            if len(found) >= MAX_CONTACTS:
                return found, skipped
        if not good:
            skipped.append(f"{n}번째 줄: 메일 주소가 올바르지 않음")
    return found, skipped


def _safe_cell(v: str) -> str:
    """Excel would run a cell starting with = + - @ as a formula."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def export_csv(book: AddressBook) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["이름", "이메일", "그룹"])
    for c in book.contacts:
        groups = ";".join(g.name for g in book.groups if c.email.lower() in (m.lower() for m in g.members))
        w.writerow([_safe_cell(c.name), c.email, _safe_cell(groups)])
    return out.getvalue().encode("utf-8-sig")
