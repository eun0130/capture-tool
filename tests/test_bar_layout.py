"""The action bar's layout model: a favourites row the person arranges, the rest grouped by
what they do, one arrangement per place (집 / 회사)."""
from capture_tool.core import bar_layout as bl
from capture_tool.core.settings import Settings, load, save


def test_BL_01_defaults_are_the_old_bar_and_work_hides_kakao():
    home = bl.default_profile("home")
    assert home.favourites == ["autosave", "text", "translate", "summarize", "table", "ppt", "mail", "kakao", "search", "pin"]
    assert home.hidden == []
    work = bl.default_profile("work")
    assert "kakao" not in work.favourites and work.hidden == ["kakao"]
    assert set(bl.NAMES) == {"copy", "more"} | {n for _, _, names in bl.GROUPS for n in names}
    assert bl.group_label("kakao") == "보내기" and bl.group_label("border") == "그림 손질" and bl.group_label("copy") == ""


def test_BL_02_rows_put_copy_first_more_last_and_group_the_rest():
    first, groups = bl.rows(bl.default_profile("home"))
    assert first == ["copy", "autosave", "text", "translate", "summarize", "table", "ppt", "mail", "kakao", "search", "pin", "more"]
    labels = [g for g, _ in groups]
    assert labels == ["저장", "보내기", "그림 손질", "화면"]            # 글자·표 is all in favourites: no empty group
    flat = [n for _, names in groups for n in names]
    assert flat == ["save_as", "open_folder", "link", "ppt_shapes", "print", "pdf", "border", "transparent", "resize",
                    "rotate_left", "rotate_right", "scroll", "help"]
    first, groups = bl.rows(bl.default_profile("work"))
    assert "kakao" not in first and "kakao" not in [n for _, names in groups for n in names]
    first, groups = bl.rows(bl.default_profile("home"), available=["copy", "more", "text", "kakao", "pdf"])
    assert first == ["copy", "text", "kakao", "more"] and groups == [("보내기", ["pdf"])]


def test_BL_03_edits_are_pure_bounded_and_ignore_nonsense():
    p = bl.default_profile("home")
    q = bl.remove_favourite(p, "kakao")
    assert "kakao" not in q.favourites and "kakao" in p.favourites            # p untouched
    assert bl.remove_favourite(q, "kakao") == q and bl.remove_favourite(q, "copy") == q
    r = bl.add_favourite(q, "pdf")
    assert r.favourites[-1] == "pdf" and bl.add_favourite(r, "pdf") == r and bl.add_favourite(r, "bogus") == r
    assert bl.add_favourite(r, "more") == r                                     # fixed ends never move
    m = bl.move_favourite(r, "pdf", -1)
    assert m.favourites[-2] == "pdf" and m.favourites[-1] == "pin"
    assert bl.move_favourite(m, "autosave", -1) == m and bl.move_favourite(r, "pdf", +1) == r   # already at the end
    h = bl.set_hidden(r, "kakao", True)
    assert h.hidden == ["kakao"] and bl.set_hidden(h, "kakao", True) == h
    assert bl.set_hidden(h, "kakao", False).hidden == []
    hf = bl.set_hidden(bl.add_favourite(q, "kakao"), "kakao", True)
    assert "kakao" not in hf.favourites                                         # hiding takes it off the favourites
    assert bl.set_hidden(p, "copy", True) == p


def test_BL_04_settings_keep_one_profile_per_place_and_clean_bad_values(tmp_path):
    s = Settings()
    assert s.workplace == "home" and s.bar_profiles == {}
    assert bl.profile_of(s, "home") == bl.default_profile("home")
    assert bl.profile_of(s, "work") == bl.default_profile("work")
    p = bl.add_favourite(bl.remove_favourite(bl.default_profile("home"), "kakao"), "border")
    bl.store_profile(s, "home", p)
    s.workplace = "work"
    save(s, tmp_path / "s.json")
    back, warnings = load(tmp_path / "s.json")
    assert warnings == [] and back.workplace == "work" and bl.profile_of(back, "home") == p
    (tmp_path / "s.json").write_text(
        '{"workplace": "moon", "bar_profiles": {"home": {"favourites": ["pdf", "copy", "bogus", "pdf"], "hidden": "x"},'
        ' "work": 5, "car": {}}}', encoding="utf-8")
    back, warnings = load(tmp_path / "s.json")
    assert back.workplace == "home"
    assert bl.profile_of(back, "home").favourites == ["pdf"] and bl.profile_of(back, "home").hidden == []
    assert bl.profile_of(back, "work") == bl.default_profile("work") and "car" not in back.bar_profiles


def test_BL_05_a_profile_round_trips_through_a_plain_dict():
    p = bl.set_hidden(bl.default_profile("home"), "print", True)
    d = bl.to_dict(p)
    assert d == {"favourites": p.favourites, "hidden": ["print"]}
    assert bl.clean(d) == p
    assert bl.clean({"favourites": ["more", "copy", "text", "text"], "hidden": ["text", "nope"]}) == bl.Profile([], ["text"])
    assert bl.clean(None) == bl.Profile([], []) and bl.clean({"favourites": "text"}) == bl.Profile([], [])
