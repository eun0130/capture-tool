"""The recent-captures strip must not sit on what the person is about to capture (BUG-115)."""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

from capture_tool.app.recent_strip import RecentStrip


def test_RSP_01_strip_goes_to_the_edge_away_from_the_mouse(qt_app):
    host = QWidget()
    host.resize(1000, 800)
    strip = RecentStrip(host, sync=True)
    strip.set_paths([])
    strip.place(QPoint(500, 700))                       # mouse low on the screen: strip at the top
    assert strip.y() == 56
    strip.place(QPoint(500, 100))                       # mouse high: strip at the bottom
    assert strip.y() > 400
    strip.place()                                       # no mouse known: bottom as before
    assert strip.y() > 400
