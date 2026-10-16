"""배경 지우기 dialog: the paper or screen background of a capture becomes transparent and the ink
is split into colour layers (검정 글씨, 빨강 도장 …) that can be kept or dropped, with a live
preview on a checkerboard. Returns the BGRA picture, or None if cancelled."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from ..core.export import apply_layers, ink_layers, on_checkerboard, remove_background

PREVIEW_BOX = 240
LEVELS = {1: "약하게 (흐린 것도 남김)", 2: "보통", 3: "세게", 4: "아주 세게 (진한 것만 남김)"}


def _pix(bgr: np.ndarray, box: int) -> QPixmap:
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h0, w0 = rgb.shape[:2]
    qi = QImage(rgb.data, w0, h0, 3 * w0, QImage.Format_RGB888)
    k = min(box / max(1, w0), box / max(1, h0), 1.0) if max(w0, h0) > box else box / max(1, max(w0, h0))
    return QPixmap.fromImage(qi).scaled(max(1, int(w0 * k)), max(1, int(h0 * k)),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation)


class TransparentDialog(QDialog):
    def __init__(self, img: np.ndarray, settings=None, parent=None):
        super().__init__(parent)
        self.img = img
        self.setWindowTitle("배경 지우기 — 글씨·사인·도장만 남기기")
        root = QVBoxLayout(self)
        root.addWidget(QLabel("종이·화면의 바탕을 지우고 글씨·사인·도장만 남깁니다. 색별로 남길 것을 고를 수 있습니다."))

        row = QHBoxLayout()
        row.addWidget(QLabel("지우는 정도:"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 4)
        self.slider.setValue(min(4, max(1, int(getattr(settings, "transparent_level", 2) or 2))))
        self.slider.setFixedWidth(160)
        self.slider.valueChanged.connect(lambda _v: self._recompute())
        row.addWidget(self.slider)
        self.level_label = QLabel()
        row.addWidget(self.level_label)
        row.addStretch(1)
        root.addLayout(row)

        self.layer_row = QHBoxLayout()
        self.layer_row.addWidget(QLabel("남길 것:"))
        self.layer_boxes: list[QCheckBox] = []
        self.layers = []
        self.layer_row.addStretch(1)
        root.addLayout(self.layer_row)

        pv = QHBoxLayout()
        self.before = QLabel(alignment=Qt.AlignCenter)
        self.after = QLabel(alignment=Qt.AlignCenter)
        for cap, lbl in (("원본", self.before), ("결과 (체크무늬 = 투명)", self.after)):
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
        root.addWidget(QLabel("올가미(K)로 사인만 따낸 뒤 쓰면 더 깔끔합니다. 결과는 투명 PNG로 복사되어 PPT·워드·그림판에 Ctrl+V 하면 뒤가 비쳐 보입니다."))

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

        self.before.setPixmap(_pix(on_checkerboard(img) if img.ndim == 3 and img.shape[2] == 4 else img[:, :, :3],
                                   PREVIEW_BOX))
        self._cut = None
        self._result = None
        self._recompute()

    # --- model -------------------------------------------------------------------------------------------
    def level(self) -> int:
        return int(self.slider.value())

    def _recompute(self) -> None:
        """A new level: the background is cut again and the colour layers found again (keeping the
        checks of layers that are still there by position)."""
        self.level_label.setText(LEVELS[self.level()])
        self._cut = remove_background(self.img, level=self.level())
        old = [b.isChecked() for b in self.layer_boxes]
        for b in self.layer_boxes:
            self.layer_row.removeWidget(b)
            b.deleteLater()
        self.layer_boxes = []
        self.layers = ink_layers(self._cut)
        for i, layer in enumerate(self.layers):
            b = QCheckBox(f"{layer.name} ({round(layer.share * 100)}%)")
            b.setStyleSheet(f"QCheckBox {{ border-left: 10px solid {layer.color}; padding-left: 6px; }}")
            b.setChecked(old[i] if i < len(old) else True)
            b.toggled.connect(lambda _on: self._update())
            self.layer_row.insertWidget(1 + i, b)
            self.layer_boxes.append(b)
        self._update()

    def _update(self) -> None:
        keep = [b.isChecked() for b in self.layer_boxes]
        self._result = apply_layers(self._cut, self.layers, keep)
        self.after.setPixmap(_pix(on_checkerboard(self._result), PREVIEW_BOX))

    def result_image(self):
        return self._result

    def chosen(self):
        return self.level(), [b.isChecked() for b in self.layer_boxes]


def ask_transparent(img, settings=None, parent=None):
    dlg = TransparentDialog(img, settings, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    level, _ = dlg.chosen()
    if settings is not None:                     # remember the level for next time
        settings.transparent_level = level
    return dlg.result_image()
