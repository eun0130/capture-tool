"""How the action bar is arranged: a favourites row the person composes (복사 always first,
전체 always last), and under 전체 every other button grouped by what it does. One arrangement
per place - 집 and 회사 - so the bar at work can differ from the bar at home."""
from __future__ import annotations

from dataclasses import dataclass

from .. import edition

FIXED_FIRST, FIXED_LAST = "copy", "more"
WORKPLACES = ("home", "work")
PLACE_NAMES = {"home": "집", "work": "회사"}

# (key, label, buttons) in the order the 전체 rows show them
GROUPS: list[tuple[str, str, list[str]]] = [
    ("save", "저장", ["autosave", "save_as", "open_folder", "link"]),
    ("read", "글자·표", ["text", "translate", "summarize", "table"]),
    ("send", "보내기", ["ppt", "ppt_shapes", "mail", "kakao", "search", "print", "pdf"]),
    ("touch", "그림 손질", ["border", "transparent", "resize", "rotate_left", "rotate_right", "scroll"]),
    ("screen", "화면", ["pin", "help"]),
]
NAMES: list[str] = [FIXED_FIRST] + [n for _, _, names in GROUPS for n in names] + [FIXED_LAST]
_GROUP_OF = {n: key for key, _, names in GROUPS for n in names}
_LABEL_OF = {n: label for _, label, names in GROUPS for n in names}
DEFAULT_FAVOURITES = ["autosave", "text", "translate", "summarize", "table", "ppt", "mail", "kakao", "search", "pin"]


@dataclass
class Profile:
    favourites: list[str]
    hidden: list[str]


def _fixed(name: str) -> bool:
    return name in (FIXED_FIRST, FIXED_LAST)


def group_key(name: str) -> str:
    """The group a button belongs to for the thin dividers (복사 sits with 저장)."""
    if name == FIXED_FIRST:
        return "save"
    return _GROUP_OF.get(name, name)


def group_label(name: str) -> str:
    return _LABEL_OF.get(name, "")


def available_names() -> list[str]:
    """Every button this edition has (the work edition has no 카톡)."""
    return [n for n in NAMES if edition.has(n)]


def default_profile(place: str) -> Profile:
    if place == "work":                      # neither messenger nor web mail is allowed at the office
        off = [n for n in NAMES if n in edition.EXCLUDED_AT_WORK]
        return Profile([n for n in DEFAULT_FAVOURITES if n not in off], off)
    return Profile(list(DEFAULT_FAVOURITES), [])


def _names(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for n in value:
        if isinstance(n, str) and n in _GROUP_OF and n not in out:
            out.append(n)
    return out


def clean(data) -> Profile:
    """A profile from a settings dict: unknown buttons, duplicates and the fixed ends dropped;
    a hidden button is never a favourite."""
    if not isinstance(data, dict):
        return Profile([], [])
    hidden = _names(data.get("hidden"))
    hidden = [n for n in NAMES if n in hidden]            # in bar order, whatever order it was saved in
    favourites = [n for n in _names(data.get("favourites")) if n not in hidden]
    return Profile(favourites, hidden)


def to_dict(p: Profile) -> dict:
    return {"favourites": list(p.favourites), "hidden": list(p.hidden)}


def rows(p: Profile, available=None) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(first row, [(group label, buttons)]) for the buttons that exist (`available`), the
    hidden ones left out, empty groups dropped."""
    avail = set(available) if available is not None else set(NAMES)
    hidden = set(p.hidden)
    first = [n for n in [FIXED_FIRST] + list(p.favourites) + [FIXED_LAST] if n in avail and n not in hidden]
    groups = []
    for _, label, names in GROUPS:
        rest = [n for n in names if n in avail and n not in hidden and n not in p.favourites]
        if rest:
            groups.append((label, rest))
    return first, groups


# --- edits (pure: a new Profile, the given one untouched) -------------------------------------------
def add_favourite(p: Profile, name: str) -> Profile:
    if name not in _GROUP_OF or name in p.favourites:
        return p
    return Profile(p.favourites + [name], [n for n in p.hidden if n != name])


def remove_favourite(p: Profile, name: str) -> Profile:
    if name not in p.favourites:
        return p
    return Profile([n for n in p.favourites if n != name], list(p.hidden))


def move_favourite(p: Profile, name: str, delta: int) -> Profile:
    if name not in p.favourites:
        return p
    i = p.favourites.index(name)
    j = i + delta
    if not 0 <= j < len(p.favourites) or j == i:
        return p
    fav = list(p.favourites)
    fav.pop(i)
    fav.insert(j, name)
    return Profile(fav, list(p.hidden))


def insert_after(p: Profile, name: str, anchor: str) -> Profile:
    """`name` becomes the favourite right after `anchor` (a drop on the row: the button before
    the blue line); after 복사 or anything that is no favourite = the front. A button that was
    no favourite joins (unhidden); a favourite moves."""
    if name not in _GROUP_OF or name == anchor:
        return p
    fav = [n for n in p.favourites if n != name]
    at = fav.index(anchor) + 1 if anchor in fav else 0
    fav.insert(at, name)
    hidden = [n for n in p.hidden if n != name]
    new = Profile(fav, hidden)
    return p if new == p else new


def set_hidden(p: Profile, name: str, on: bool) -> Profile:
    if name not in _GROUP_OF or on == (name in p.hidden):
        return p
    if on:
        return Profile([n for n in p.favourites if n != name], p.hidden + [name])
    return Profile(list(p.favourites), [n for n in p.hidden if n != name])


# --- settings ---------------------------------------------------------------------------------------
def profile_of(settings, place: str) -> Profile:
    """The arrangement saved for a place, or that place's default."""
    data = getattr(settings, "bar_profiles", None) or {}
    if isinstance(data, dict) and isinstance(data.get(place), dict):
        return clean(data[place])
    return default_profile(place)


def store_profile(settings, place: str, p: Profile) -> None:
    data = dict(getattr(settings, "bar_profiles", None) or {})
    data[place] = to_dict(clean(to_dict(p)))
    settings.bar_profiles = data
