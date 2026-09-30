"""Scroll capture of PDF-viewer-like views (user report: stops midway where images or separators
are). Each case must reach the end with every page exactly once and in order."""
import numpy as np
import pytest

from capture_tool.core.scroll_session import ScrollCapture
from tests.pdfsim import SIDEBAR, PdfView, marker_sequence


def capture(view: PdfView, **kw):
    sc = ScrollCapture(grab=view.frame, wheel=view.wheel, **kw)
    for _ in sc.run():
        pass
    return sc, sc.result()


def all_pages_once(view: PdfView, img) -> bool:
    return marker_sequence(img) == list(range(len(view.pages)))


def no_sidebar(img) -> bool:
    return not (np.abs(img.astype(int) - SIDEBAR).max(axis=2) <= 2).any()


def test_PDF_01_plain_pages_with_gaps_and_margins():
    v = PdfView()
    sc, out = capture(v)
    assert sc.reason == "end" and all_pages_once(v, out)


def test_PDF_02_thumbnail_sidebar_that_does_not_scroll():
    """Chrome/Edge PDF viewer: thumbnails on the left stay put, the highlight moves."""
    v = PdfView(sidebar=160)
    sc, out = capture(v)
    assert sc.reason == "end", sc.reason
    assert all_pages_once(v, out)
    assert no_sidebar(out[v.toolbar:])                      # the static panel is not repeated


def test_PDF_03_photos_render_slightly_differently_each_time():
    v = PdfView(jitter_photo=True)
    sc, out = capture(v)
    assert sc.reason == "end" and all_pages_once(v, out)


def test_PDF_04_blank_page_longer_than_the_overlap():
    v = PdfView(blank=(1, 2), page_h=900)
    sc, out = capture(v)
    assert sc.reason == "end" and all_pages_once(v, out)


def test_PDF_05_pages_drawn_late_after_scrolling():
    v = PdfView(lazy_grabs=2)
    sc, out = capture(v)
    assert sc.reason == "end" and all_pages_once(v, out)


def test_PDF_06_page_number_badge_changes_while_scrolling():
    v = PdfView(badge=True)
    sc, out = capture(v)
    assert sc.reason == "end" and all_pages_once(v, out)


def test_PDF_07_everything_together():
    v = PdfView(sidebar=160, jitter_photo=True, badge=True, blank=(2,), lazy_grabs=1)
    sc, out = capture(v)
    assert sc.reason == "end", sc.reason
    assert all_pages_once(v, out) and no_sidebar(out[v.toolbar:])


def test_PDF_08_from_the_top_of_a_document_opened_in_the_middle():
    v = PdfView(sidebar=160, start=1500)
    sc, out = capture(v, to_top=True)
    assert sc.reason == "end" and all_pages_once(v, out)


@pytest.mark.parametrize("px", [23, 60, 140])
def test_PDF_09_any_scroll_step_size(px):
    v = PdfView(sidebar=120, px_per_notch=px)
    sc, out = capture(v)
    assert sc.reason == "end" and all_pages_once(v, out)


def test_PDF_10_height_matches_the_document():
    v = PdfView(sidebar=160)
    _, out = capture(v)
    assert abs(out.shape[0] - (v.toolbar + v.doc.shape[0])) <= 4
