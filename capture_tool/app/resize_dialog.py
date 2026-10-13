"""크기 줄이기 dialog: presets, a live before/after preview and the estimated file size. Returns
(resized BGR image, "png"|"jpg") or None if cancelled."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QVBoxLayout, QWidget)

from ..core.export import estimate_bytes, resize_longest, resize_percent, resize_to_bytes

PREVIEW_BOX = 240          # px; the before thumbnail fills this; the after is drawn proportionally


def _human(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 1_000_000 else f"{max(1, n // 1000)} KB"


def _pix(img: np.ndarray, w: int) -> QPixmap:
    bgr = img[:, :, :3] if img.ndim == 3 else np.stack([img] * 3, -1)
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h0, w0 = rgb.shape[:2]
    qi = QImage(rgb.data, w0, h0, 3 * w0, QImage.Format_RGB888)
    return QPixmap.fromImage(qi).scaledToWidth(max(1, w), Qt.SmoothTransformation)


class ResizeDialog(QDialog):
    def __init__(self, img: np.ndarray, settings=None, parent=None):
        super().__init__(parent)
        self.img = img[:, :, :3] if img.ndim == 3 else img
        self.fmt = "jpg" if getattr(settings, "image_format", "png") == "jpg" else "png"
        h, w = self.img.shape[:2]
        self.setWindowTitle(f"크기 줄이기 — 원본 {w} × {h}px ({_human(estimate_bytes(self.img, self.fmt))})")
        root = QVBoxLayout(self)

        self.presets = [("원본 (100%)", lambda im: im),
                        ("긴 쪽 1280px", lambda im: resize_longest(im, 1280)),
                        ("50%", lambda im: resize_percent(im, 50)),
                        ("25%", lambda im: resize_percent(im, 25)),
                        ("용량 1MB 이하", lambda im: resize_to_bytes(im, 1_000_000, self.fmt)[0])]
        row = QHBoxLayout()
        self.group = QButtonGroup(self)
        for i, (label, _) in enumerate(self.presets):
            rb = QRadioButton(label)
            rb.setChecked(i == 1)
            self.group.addButton(rb, i)
            row.addWidget(rb)
        row.addStretch(1)
        self.group.idToggled.connect(lambda i, on: self._update() if on else None)
        root.addLayout(row)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("형식:"))
        self.fmt_group = QButtonGroup(self)
        for i, name in enumerate(("png", "jpg")):
            rb = QRadioButton("PNG (또렷)" if name == "png" else "JPG (작게)")
            rb.setChecked(name == self.fmt)
            self.fmt_group.addButton(rb, i)
            fmt_row.addWidget(rb)
        fmt_row.addStretch(1)
        self.fmt_group.idToggled.connect(self._fmt_changed)
        root.addLayout(fmt_row)

        pv = QHBoxLayout()
        self.before = QLabel(alignment=Qt.AlignCenter)
        self.after = QLabel(alignment=Qt.AlignCenter)
        for cap, lbl in (("원본", self.before), ("줄인 결과", self.after)):
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

        self.info = QLabel(alignment=Qt.AlignCenter)
        root.addWidget(self.info)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("이 크기로 복사·저장")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._before_pix = _pix(self.img, PREVIEW_BOX)
        self.before.setPixmap(self._before_pix)
        self._result = self.img
        self._update()

    def _fmt_changed(self, i, on):
        if on:
            self.fmt = ("png", "jpg")[i]
            self._update()

    def result_image(self):
        return self._result, self.fmt

    def _update(self):
        self._result = self.presets[self.group.checkedId()][1](self.img)
        h, w = self._result.shape[:2]
        oh, ow = self.img.shape[:2]
        ratio = w / max(1, ow)
        self.after.setPixmap(_pix(self._result, max(1, int(PREVIEW_BOX * ratio))))   # drawn proportionally
        n = estimate_bytes(self._result, self.fmt)
        self.info.setText(f"{ow} × {oh}  →  <b>{w} × {h}px</b>   ·   예상 용량 약 <b>{_human(n)}</b> ({self.fmt.upper()})")


def ask_resize(img, settings=None, parent=None):
    dlg = ResizeDialog(img, settings, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    return dlg.result_image()
