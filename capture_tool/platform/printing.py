"""Send a capture to a printer via Qt (offline, no external program). Shows the system print
dialog; the picture is scaled to fit the page, keeping its ratio."""
from __future__ import annotations

import numpy as np


def print_image(img: np.ndarray, dpi: float = 96, dialog_factory=None, printer_factory=None) -> bool:
    """Open the print dialog and print `img`. Returns False if the person cancelled. The two
    factories are injected by tests; in the app they default to the real Qt classes."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtPrintSupport import QPrinter, QPrintDialog
    from PySide6.QtWidgets import QDialog

    printer = (printer_factory or (lambda: QPrinter(QPrinter.HighResolution)))()
    dlg = (dialog_factory or (lambda p: QPrintDialog(p)))(printer)
    if dlg.exec() != QDialog.Accepted:
        return False
    bgr = img[:, :, :3] if img.ndim == 3 else np.stack([img] * 3, -1)
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    painter = QPainter(printer)
    try:
        rect = painter.viewport()
        scaled = qimg.size()
        from PySide6.QtCore import Qt as _Qt
        scaled.scale(rect.size(), _Qt.KeepAspectRatio)
        painter.setViewport(rect.x(), rect.y(), scaled.width(), scaled.height())
        painter.setWindow(qimg.rect())
        painter.drawImage(0, 0, qimg)
    finally:
        painter.end()
    return True
