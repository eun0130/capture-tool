"""Two editions from one source. 집용 has everything; 회사용 (the work installer, published from
its own repository) has no KakaoTalk at all - no button, no guide page, no code path - so a
company PC never shows it, whatever the settings say."""
import sys
from pathlib import Path

import pytest

from capture_tool import edition
from capture_tool.app import guide
from tests.test_app import drag, make  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def work(monkeypatch):
    monkeypatch.setenv("CAPTURE_EDITION", "work")


def test_ED_01_default_is_home_the_marker_or_env_says_work(monkeypatch, tmp_path):
    monkeypatch.delenv("CAPTURE_EDITION", raising=False)
    monkeypatch.setattr(edition, "_MARKER", tmp_path / "edition.txt")
    edition.reset()
    assert edition.current() == "home" and edition.has_kakao() and not edition.is_work()
    assert edition.title() == "캡처 도구"
    (tmp_path / "edition.txt").write_text("work\n", encoding="utf-8")
    edition.reset()
    assert edition.current() == "work" and not edition.has_kakao() and edition.title() == "캡처 도구 (회사용)"
    (tmp_path / "edition.txt").write_text("whatever", encoding="utf-8")
    edition.reset()
    assert edition.current() == "home"                       # anything but "work" is the full edition
    monkeypatch.setenv("CAPTURE_EDITION", "work")
    assert edition.current() == "work"                       # the environment wins (tests, a dev run)
    monkeypatch.setenv("CAPTURE_EDITION", "nonsense")
    assert edition.current() == "home"
    edition.reset()


def test_ED_02_the_work_edition_has_no_kakao_button(make, work):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert "kakao" not in ov.side_bar.buttons and "mail" not in ov.side_bar.buttons
    assert "ppt" in ov.side_bar.buttons and "search" in ov.side_bar.buttons
    assert ov.side_bar.layout_first[0] == "copy" and "kakao" not in ov.side_bar.layout_first
    c.on_toolbar_action("kakao_main")                        # nothing to send to: ignored, no crash
    assert not any("카카오" in m for m in c.messages)


def test_ED_03_the_work_guide_never_mentions_kakao_or_mail(work):
    pages = guide.pages()
    assert len(pages) == len(guide.PAGES) - 2                # no KakaoTalk chapter, no mail chapter
    text = "\n".join(p.title + p.intro + "".join(p.steps) + p.tip for p in pages)
    assert "카톡" not in text and "카카오" not in text
    assert "메일" not in text.replace("이메일", "")           # (이메일 = the personal-data masking, stays)
    assert any("검색" in p.title for p in pages)             # the rest is there


def test_ED_03b_the_home_guide_is_the_full_one(monkeypatch):
    monkeypatch.setenv("CAPTURE_EDITION", "home")
    assert guide.pages() == list(guide.PAGES)


def test_ED_04_the_build_makes_both_installers_and_publishes_the_work_one_apart():
    ps = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert "$Edition" in ps and "edition.txt" in ps
    iss = (ROOT / "installer" / "CaptureTool.iss").read_text(encoding="utf-8")
    assert "CaptureTool-Work-Setup" in iss and "회사용" in iss
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    assert "edition.txt" in spec
    yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "-Edition work" in yml and "eun0130/capture_work" in yml and "WORK_REPO_TOKEN" in yml
    assert "CaptureTool-Setup-*.exe" in yml                  # the home release carries only its own installer
    assert "edition.txt" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert not (ROOT / "capture_tool" / "edition.txt").exists()   # never left behind in the source tree


def test_ED_07_an_installed_build_ignores_the_environment_and_bundles_no_kakao_or_mail_code(monkeypatch, tmp_path):
    """Review finding: a runtime switch could be flipped back on a company PC. Frozen builds
    take the edition from the marker only, and the work bundle has no KakaoTalk / mail modules."""
    monkeypatch.setattr(edition, "_MARKER", tmp_path / "edition.txt")
    (tmp_path / "edition.txt").write_text("work", encoding="utf-8")
    edition.reset()
    monkeypatch.setenv("CAPTURE_EDITION", "home")
    assert edition.current() == "home"                       # from source: the variable wins (tests, dev runs)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert edition.current() == "work"                       # installed: the marker, whatever the environment says
    monkeypatch.delattr(sys, "frozen", raising=False)
    edition.reset()
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    assert "capture_tool.platform.kakao" in spec and "capture_tool.app.mail_ui" in spec and "excludes += WORK_EXCLUDES" in spec


def test_ED_08_the_work_edition_sends_nothing_to_the_internet(work):
    """No web search, no internet share link, no Gemini on a company PC - the modules are not
    even in the bundle; the 검색 and 링크 buttons stay (saved-capture search, file link)."""
    from capture_tool.core import bar_layout as bl
    assert edition.excluded() == ("kakao", "mail", "search_web", "link_web", "gemini")
    assert not edition.has_web_search() and not edition.has_share() and not edition.has_gemini()
    assert "search" in bl.available_names() and "link" in bl.available_names()
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    for mod in ("capture_tool.core.websearch", "capture_tool.platform.lens", "capture_tool.core.gemini"):
        assert mod in spec
    assert "capture_tool.core.share" not in spec               # file_link stays (nothing uploaded)


def test_ED_08b_the_home_edition_keeps_them(monkeypatch):
    monkeypatch.setenv("CAPTURE_EDITION", "home")
    assert edition.has_web_search() and edition.has_share() and edition.has_gemini()


def test_ED_09_the_work_controller_ignores_web_search_and_the_share_link(make, work):
    c = make()
    c.uploader = lambda *a, **k: pytest.fail("the capture was uploaded")
    c.ask_share_consent = lambda: pytest.fail("the share consent dialog opened")
    c._open_search = lambda *a, **k: pytest.fail("a web search page was opened")
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    for action in ("search_img:google", "search_text:google", "search_text:naver", "search_text:papago", "link_web"):
        c.on_toolbar_action(action)
        assert "회사용" in c.messages[-1]
    assert c.session.state.name == "EDITING"                   # the capture stays open
    assert c.settings.share_consent is False


def test_ED_09b_the_work_controller_summarises_with_the_company_llm(make, work):
    from capture_tool.core.company_llm import CompanyLLM, CompanyLLMError
    from capture_tool.core.settings import Settings
    c = make(settings=Settings(ai_endpoint="https://llm.corp.local", ai_model="corp-chat"))
    svc = c.ai
    assert svc.cloud_name == "회사 AI"
    engine = svc.cloud_factory("k")
    assert isinstance(engine, CompanyLLM) and engine.endpoint == "https://llm.corp.local" and engine.model == "corp-chat"
    assert "Gemini" not in svc._cloud()[1]                     # no key: the note names the company AI
    c2 = make()                                                # no server address yet: nothing is sent
    with pytest.raises(CompanyLLMError) as e:
        c2.ai.cloud_factory("k").generate("x")
    assert e.value.kind == "config"


def test_ED_10_work_settings_and_guide_know_no_gemini_share_or_web_search(qt_app, work):
    from capture_tool.app.settings_dialog import SettingsDialog
    from capture_tool.core.settings import Settings
    d = SettingsDialog(Settings(ai_endpoint="https://llm.corp.local", ai_model="corp-chat"))
    assert d.has_share_section is False and d.has_gemini is False
    assert "회사 AI" in d.ai_cloud.text() and "Gemini" not in d.ai_cloud.text() and "Gemini" not in d.ai_cloud_translate.text()
    assert "llm.corp.local" in d.ai_key_status.text()
    s = d.result_settings()
    assert (s.ai_endpoint, s.ai_model) == ("https://llm.corp.local", "corp-chat")
    text = "\n".join(p.title + p.intro + "".join(p.steps) + p.tip for p in guide.pages())
    for word in ("구글", "네이버", "파파고", "렌즈", "Gemini", "Google", "인터넷 공유"):
        assert word not in text, word
    assert "내 캡처" in text and len(guide.pages()) == len(guide.PAGES) - 2


def test_ED_10b_the_home_guide_also_tells_about_searching_saved_captures(monkeypatch):
    monkeypatch.setenv("CAPTURE_EDITION", "home")
    nine = next(p for p in guide.pages() if p.title.startswith("9."))
    assert "내 캡처" in "".join(nine.steps) and "구글" in "".join(nine.steps)


def test_ED_11_work_side_bar_search_and_link_go_straight_to_local(make, work):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    got = []
    ov.side_bar.action.connect(got.append)
    ov.side_bar.buttons["search"].click()
    assert got[-1] == "search_local"
    ov.side_bar._link_menu(ov.side_bar.buttons["search"])      # the link menu is skipped: the file link at once
    assert got[-1] == "link_file"


def test_ED_12_the_work_key_dialog_sets_up_the_company_server(qt_app, work):
    from capture_tool.app.ai_ui import KeyDialog, consent_text, engine_label
    from capture_tool.core.settings import Settings
    from capture_tool.platform.secret import unprotect
    s = Settings()
    checked = []
    dlg = KeyDialog(s, check=lambda k: checked.append(k), sync=True)
    assert dlg.work and "open" not in dlg.buttons
    dlg.on_clipboard("sk-corp-123")                           # no address yet: nothing is checked
    assert checked == [] and "주소" in dlg.status.text()
    dlg.endpoint.setText("https://llm.corp.local/v1/")
    dlg.model.setText(" corp-chat ")
    dlg.on_clipboard("AIza-not-needed sk-corp-123")            # a company key is one word
    assert checked == []
    dlg.on_clipboard("sk-corp-123")
    assert checked == ["sk-corp-123"] and dlg.ok
    dlg.save()
    assert unprotect(s.ai_key) == "sk-corp-123" and s.ai_endpoint == "https://llm.corp.local" and s.ai_model == "corp-chat"
    assert engine_label("cloud") == "회사 AI (회사 서버)"
    assert "llm.corp.local" in consent_text("https://llm.corp.local") and "Google" not in consent_text("x")


def test_ED_05_the_work_edition_is_always_at_work(make, work):
    from capture_tool.core.settings import Settings
    c = make(settings=Settings(workplace="home"))
    assert c.workplace() == "work"                           # no 집 switch in the work edition
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert ov.side_bar.place_label.isVisible() is False      # nothing to tell apart: no "회사" badge


def test_ED_06_the_work_edition_has_no_mail_either(make, work):
    """Neither KakaoTalk nor web mail is allowed on a company PC: no 메일 button, no mail
    settings, the action ignored; and the home edition at 회사 hides both by default."""
    from capture_tool.app.settings_dialog import SettingsDialog
    from capture_tool.core import bar_layout as bl
    from capture_tool.core.settings import Settings
    assert not edition.has("mail") and not edition.has("kakao") and edition.has("ppt")
    assert edition.excluded()[:2] == ("kakao", "mail")
    assert "mail" not in bl.available_names() and "kakao" not in bl.available_names()
    c = make()
    c.ask_mail = lambda *a, **k: pytest.fail("the mail picker opened")
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert "mail" not in ov.side_bar.buttons
    c.on_toolbar_action("mail")
    assert c.mail_helper is None
    d = SettingsDialog(Settings())
    assert d.has_mail_section is False
    assert d.result_settings().mail_provider == ""
    assert bl.default_profile("work").hidden == ["mail", "kakao"]
