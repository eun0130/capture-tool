"""Inline stroke icons (24x24 SVG) rendered to QIcon."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "select": '<path d="M5 3l14 8-6 2-3 6z"/>',
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8" ry="6"/>',
    "line": '<path d="M5 19L19 5"/>',
    "arrow": '<path d="M5 19L19 5M10 5h9v9"/>',
    "curve": '<path d="M4 18C8 4 16 20 20 6"/>',
    "pen": '<path d="M4 20l4-1 11-11-3-3L5 16z"/>',
    "text": '<path d="M6 5h12M12 5v14"/>',
    "step": '<circle cx="12" cy="12" r="8"/><path d="M10.5 9.5L12.5 8v8"/>',
    "highlight": '<path d="M9 14l-4 5h5l2-2M9 14l7-9 3 3-7 9z"/>',
    "mosaic": '<rect x="4" y="4" width="16" height="16"/><path d="M4 12h16M12 4v16"/>'
              '<rect x="4" y="4" width="8" height="8" fill="{c}"/><rect x="12" y="12" width="8" height="8" fill="{c}"/>',
    "fill": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="8" y="8" width="8" height="8" fill="{c}"/>',
    "ocr": '<path d="M4 8V5h3M17 5h3v3M20 16v3h-3M7 19H4v-3M8 10h8M8 14h5"/>',
    "shapes": '<rect x="3" y="11" width="8" height="8"/><circle cx="16" cy="8" r="4"/>',
    "undo": '<path d="M9 8L5 12l4 4M5 12h10a4 4 0 010 8h-3"/>',
    "redo": '<path d="M15 8l4 4-4 4M19 12H9a4 4 0 000 8h3"/>',
    "pin": '<path d="M9 4h6l-1 5 3 3H7l3-3zM12 12v8"/>',
    "save": '<path d="M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "capture": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/>',
}


def svg(name: str, color: str = "#343A40") -> str:
    body = _P[name].replace("{c}", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def icon(name: str, color: str = "#343A40", size: int = 40) -> QIcon:
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p)
    p.end()
    return QIcon(pm)
