"""테두리 · 음영 dialog: pick a border thickness, a colour and an optional drop shadow, with a
live before/after preview. Returns the framed BGR image, or None if cancelled."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from ..core.export import add_border

PREVIEW_BOX = 240
THICKNESS = [("없음", 0), ("얇게", 3), ("보통", 8), ("두껍게", 16)]
SWATCHES = [("흰색", "#FFFFFF"), ("검정", "#111111"), ("회색", "#AAAAAA"),
            ("파랑", "#3B7CF6"), ("빨강", "#E03131")]


def _hex_to_bgr(h: str):
    s = h.lstrip("#")
    return (int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16))


def _pix(img: np.ndarray, box: int) -> QPixmap:
    bgr = img[:, :, :3] if img.ndim == 3 else np.stack([img] * 3, -1)
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h0, w0 = rgb.shape[:2]
    qi = QImage(rgb.data, w0, h0, 3 * w0, QImage.Format_RGB888)
    k = min(box / max(1, w0), box / max(1, h0), 1.0) if max(w0, h0) > box else box / max(1, max(w0, h0))
    return QPixmap.fromImage(qi).scaled(max(1, int(w0 * k)), max(1, int(h0 * k)),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation)


class BorderDialog(QDialog):
    def __init__(self, img: np.ndarray, settings=None, parent=None):
        super().__init__(parent)
        self.img = img[:, :, :3] if img.ndim == 3 else img
        self.setWindowTitle("테두리 · 음영")
        self.color = getattr(settings, "border_color", "#FFFFFF")
        start_t = getattr(settings, "border_thickness", 8)
        start_shadow = getattr(settings, "border_shadow", False)
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("굵기:"))
        self.group = QButtonGroup(self)
        start_i = max((i for i, (_, v) in enumerate(THICKNESS) if v <= start_t), default=0)
        for i, (label, _) in enumerate(THICKNESS):
            rb = QRadioButton(label)
            rb.setChecked(i == start_i)
            self.group.addButton(rb, i)
            row.addWidget(rb)
        row.addStretch(1)
        self.group.idToggled.connect(lambda i, on: self._update() if on else None)
        root.addLayout(row)

        crow = QHBoxLayout()
        crow.addWidget(QLabel("색:"))
        self.swatch_group = QButtonGroup(self)
        self.swatch_hex = [h for _, h in SWATCHES]
        for i, (label, _) in enumerate(SWATCHES):
            rb = QRadioButton(label)
            rb.setChecked(self.swatch_hex[i].lower() == self.color.lower())
            self.swatch_group.addButton(rb, i)
            crow.addWidget(rb)
        if not any(b.isChecked() for b in self.swatch_group.buttons()):
            self.swatch_group.buttons()[0].setChecked(True)
            self.color = self.swatch_hex[0]
        self.swatch_group.idToggled.connect(self._swatch_changed)
        pick = QPushButton("색 선택…")
        pick.clicked.connect(self._pick_colour)
        crow.addWidget(pick)
        crow.addStretch(1)
        root.addLayout(crow)

        self.shadow = QCheckBox("음영(그림자) 넣기")
        self.shadow.setChecked(bool(start_shadow))
        self.shadow.toggled.connect(lambda _on: self._update())
        root.addWidget(self.shadow)

        pv = QHBoxLayout()
        self.before = QLabel(alignment=Qt.AlignCenter)
        self.after = QLabel(alignment=Qt.AlignCenter)
        for cap, lbl in (("원본", self.before), ("결과", self.after)):
            box = QVBoxLayout()
            box.addWidget(QLabel(cap, alignment=Qt.AlignCenter))
            holder = QWidget()
            holder.setFixedSize(PREVIEW_BOX + 20, PREVIEW_BOX + 20)
            hv = QVBoxLayout(holder)
            hv.setAlignment(Qt.AlignCenter)
            hv.addWidget(lbl)
            box.addWidget(holder)
            pv.addLayout(box)
        root.addLayout(pv)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("이대로 복사·저장")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self.before.setPixmap(_pix(self.img, PREVIEW_BOX))
        self._result = self.img
        self._update()

    def _swatch_changed(self, i, on):
        if on:
            self.color = self.swatch_hex[i]
            self._update()

    def _pick_colour(self):
        from .toolbar import colour_dialog
        dlg = colour_dialog(self, self.color, "테두리 색")
        if dlg.exec() != QColorDialog.Accepted or not dlg.selectedColor().isValid():
            dlg.deleteLater()
            return
        c = dlg.selectedColor()
        dlg.deleteLater()
        if c.isValid():
            self.color = c.name()
            for b in self.swatch_group.buttons():
                b.setChecked(False)
            self._update()

    def thickness(self) -> int:
        return THICKNESS[self.group.checkedId()][1]

    def result_image(self):
        return self._result

    def chosen(self):
        return self.thickness(), self.color, self.shadow.isChecked()

    def _update(self):
        self._result = add_border(self.img, thickness=self.thickness(),
                                  color=_hex_to_bgr(self.color), shadow=self.shadow.isChecked())
        self.after.setPixmap(_pix(self._result, PREVIEW_BOX))


def ask_border(img, settings=None, parent=None):
    dlg = BorderDialog(img, settings, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    t, color, shadow = dlg.chosen()
    if settings is not None:                     # remember the choice for next time
        settings.border_thickness, settings.border_color, settings.border_shadow = t, color, shadow
    return dlg.result_image()
