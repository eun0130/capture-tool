"""Beginner's guide: one source shown as a pop-up window in the app (도움말 button, F1, tray menu,
first start) and written to docs/QUICK_START.md - kept identical by this test."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from capture_tool.app import guide
from tests.test_app import drag, make  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parents[1]


def test_GUIDE_01_pages_are_complete_and_ordered():
    titles = [p.title for p in guide.PAGES]
    assert len(titles) >= 10 and len(set(titles)) == len(titles)
    assert titles[0].startswith("1.") and all(p.steps for p in guide.PAGES)
    assert all(len(s) <= 140 for p in guide.PAGES for s in p.steps)              # short, followable steps


def test_GUIDE_02_every_bar_button_is_explained():
    from capture_tool.app.side_bar import ACTIONS
    text = guide.as_markdown()
    for name, _, label, _, _ in ACTIONS:
        assert label in text, label


def test_GUIDE_03_document_matches_the_app():
    doc = (ROOT / "docs" / "QUICK_START.md").read_text(encoding="utf-8")
    assert doc == guide.as_markdown(), "run: python tools/make_quick_start.py"


def test_GUIDE_04_window_pages_and_navigation(qt_app):
    w = guide.GuideWindow()
    assert w.list.count() == len(guide.PAGES) and w.list.currentRow() == 0
    assert guide.PAGES[0].title in w.body.toPlainText()
    w.next.click()
    assert w.list.currentRow() == 1 and guide.PAGES[1].title in w.body.toPlainText()
    w.prev.click()
    assert w.list.currentRow() == 0 and not w.prev.isEnabled()
    w.show_page(len(guide.PAGES) - 1)
    assert not w.next.isEnabled()
    w.show_topic("메일")
    assert "메일" in guide.PAGES[w.list.currentRow()].title


def test_GUIDE_05_help_button_and_f1_open_the_guide(make):
    c = make()
    c.start_capture()
    ov = c.overlays[0]
    drag(ov, (100, 100), (500, 400))
    assert "help" in ov.side_bar.buttons
    ov.side_bar.trigger("help")
    assert c.guide_window is not None and c.guide_window.isVisible()
    c.guide_window.close()
    QTest.keyClick(ov, Qt.Key_F1)
    assert c.guide_window.isVisible()


def test_GUIDE_06_first_start_shows_the_guide_once(make):
    c = make()
    assert c.settings.guide_shown is False
    assert c.show_guide_first_time() is True and c.guide_window.isVisible()
    c.guide_window.close()
    assert c.settings.guide_shown is True and c.show_guide_first_time() is False


def test_GUIDE_07_guide_setting_is_saved(tmp_path):
    from capture_tool.core.settings import Settings, load, save
    s = Settings()
    s.guide_shown = True
    save(s, tmp_path / "s.json")
    assert load(tmp_path / "s.json")[0].guide_shown is True


# --- pictures (v0.7.5): only where a picture explains faster ------------------------------------
PKG_IMG = ROOT / "capture_tool" / "app" / "guide_images"
DOC_IMG = ROOT / "docs" / "images" / "guide"


def test_GUIDE_08_a_few_pages_have_a_picture_in_app_and_document():
    with_img = [p for p in guide.PAGES if p.image]
    assert 3 <= len(with_img) <= 6                                   # helpful, not overdone
    for p in with_img:
        a, b = PKG_IMG / p.image, DOC_IMG / p.image
        assert a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes(), p.image
        assert f"](images/guide/{p.image})" in guide.as_markdown()


def test_GUIDE_09_pictures_are_small_and_readable():
    import cv2
    for p in guide.PAGES:
        if p.image:
            f = PKG_IMG / p.image
            img = cv2.imread(str(f))
            assert img is not None and 200 <= img.shape[1] <= 900 and f.stat().st_size < 250_000, p.image


def test_GUIDE_10_window_shows_the_picture(qt_app):
    w = guide.GuideWindow()
    i = next(i for i, p in enumerate(guide.PAGES) if p.image)
    w.show_page(i)
    assert "<img" in w.body.toHtml() and guide.image_path(guide.PAGES[i].image).is_file()


def test_GUIDE_11_installer_carries_the_pictures():
    spec = (ROOT / "packaging" / "capture_tool.spec").read_text(encoding="utf-8")
    assert "guide_images" in spec
