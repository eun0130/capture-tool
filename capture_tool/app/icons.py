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
    "lasso": '<path d="M7 17C3 14 3 8 8 6s11-1 12 3-4 7-9 7" stroke-dasharray="2.5 2.5"/><path d="M9 16l-3 5 5-2z"/>',
    "fill": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="8" y="8" width="8" height="8" fill="{c}"/>',
    "translate": '<path d="M4 6h8M8 4v2M10.5 6c-.8 3.2-3 5.8-6 7.2M6 9c1 2 2.6 3.4 4.6 4.2"/>'
                 '<path d="M12.5 20l4-9 4 9M14 17h5"/>',
    "summary": '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4"/>',
    "ocr": '<path d="M4 8V5h3M17 5h3v3M20 16v3h-3M7 19H4v-3M8 10h8M8 14h5"/>',
    "shapes": '<rect x="3" y="11" width="8" height="8"/><circle cx="16" cy="8" r="4"/>',
    "undo": '<path d="M9 8L5 12l4 4M5 12h10a4 4 0 010 8h-3"/>',
    "redo": '<path d="M15 8l4 4-4 4M19 12H9a4 4 0 000 8h3"/>',
    "scroll": '<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M12 8v8M9 13l3 3 3-3"/>',
    "link": '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
    "pin": '<path d="M9 4h6l-1 5 3 3H7l3-3zM12 12v8"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 014.8.9c0 1.7-2.4 2-2.4 3.6M12 17h.01"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "more": '<circle cx="5" cy="12" r="1.6" fill="{c}"/><circle cx="12" cy="12" r="1.6" fill="{c}"/>'
            '<circle cx="19" cy="12" r="1.6" fill="{c}"/>',
    "folder": '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "table": '<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M3 10h18M3 14.5h18M9 5v14M15 5v14"/>',
    "talk": '<path d="M12 4c-4.7 0-8.5 3-8.5 6.6 0 2.3 1.5 4.3 3.8 5.5L6.5 20l4.2-2.9c.4 0 .9.1 1.3.1 '
            '4.7 0 8.5-3 8.5-6.6S16.7 4 12 4z"/>',
    "save": '<path d="M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "capture": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/>',
    "ppt": '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M12 16v4M8 20h8M7 12l3-3 3 2 4-4"/>',
    "save_as": '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><path d="M12 10v6M9 13l3 3 3-3"/>',
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
