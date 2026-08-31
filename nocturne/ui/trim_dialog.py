"""Trim — cut the edges off a finished image without losing the edit.

You crop at the start, on a linear frame, before you can see what you have. Then
you process for twenty minutes and find a ragged stacking border or a smeared
corner that was invisible before the stretch. Going back to the Crop step would
work, but Project.run_step truncates forward history, so it destroys every
processing step after it — redoing an hour of work to remove twenty pixels.

Trim is a FINISHING operation, not a pipeline step. It appends a geometry step at
the end of history rather than reaching back, so nothing is truncated, undo still
works, and the provenance record survives. That distinction is the whole design:
the pipeline pins Crop to the front for a real reason (background extraction,
Stretch and auto Levels all derive parameters from whole-frame statistics, which
are better measured on the region you kept), but a late trim is not asking for
any of that to be recomputed.

A dialog rather than the main canvas: _setup_crop_overlay is bound to the Crop
STAGE, and a tool usable at any point after Stretch should not have to fight the
canvas for its crop mode. Share drives set_crop_overlay inside its own dialog the
same way.
"""
from __future__ import annotations

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ..core.crop import ASPECT_RATIOS, ASPECTS, GUIDE_KINDS, GUIDES

from .image_view import ImageView
from .preview import to_qimage


class TrimDialog(QDialog):
    """Pick a region of the current image to keep. `bounds()` is the chosen
    (top, bottom, left, right) once accepted, or None if nothing was chosen."""

    def __init__(self, img, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trim")
        self.setMinimumSize(720, 520)
        self.resize(1000, 720)
        self._img = img
        self._bounds: tuple[int, int, int, int] | None = None

        h, w = img.data.shape[:2]
        self._full = (0, h, 0, w)

        self.view = ImageView()
        self.view.set_image(to_qimage(img))
        # Box shown immediately at the full frame: unlike the Crop step, there is
        # no content-detection to offer here — the edges the user wants gone are
        # ones only they can see.
        self.view.set_crop_overlay(True, content_bounds=self._full, aspect_ratio=None)
        self.view.show_crop_box()
        self.view.cropBoxChanged.connect(lambda *_: self._refresh())

        self.size_label = QLabel()
        self.size_label.setObjectName("stepExplainer")
        self.hint = QLabel("Drag the edges to remove what you don't want. "
                            "Your edit is kept — this is added as a final step.")
        self.hint.setObjectName("stepExplainer")
        self.hint.setWordWrap(True)

        # The same aspect and guide affordances the Crop step has. Trim was
        # shipped with a bare rubber-band box, and Andreas (2026-08-31): "it's
        # kind of difficult to do a meaningful trim". ImageView already has all
        # of it — eight handles, apply_aspect, set_guides — Trim simply never
        # wired a control to any of it.
        self.aspect_box = QComboBox()
        self.aspect_box.addItems(ASPECTS)
        self.aspect_box.currentTextChanged.connect(
            lambda t: self.view.apply_aspect(ASPECT_RATIOS[t]))
        self.guides_box = QComboBox()
        self.guides_box.addItems(GUIDES)
        self.guides_box.currentTextChanged.connect(
            lambda t: self.view.set_guides(GUIDE_KINDS[t]))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Aspect ratio"))
        controls.addWidget(self.aspect_box)
        controls.addSpacing(16)
        controls.addWidget(QLabel("Guides"))
        controls.addWidget(self.guides_box)
        controls.addStretch(1)

        self.apply_btn = QPushButton("Apply Trim")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.size_label)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.hint)
        root.addLayout(controls)
        root.addWidget(self.view, 1)
        root.addLayout(buttons)
        self._refresh()

    # --- state ---
    def _current(self) -> tuple[int, int, int, int]:
        if self.view.crop_box_visible():
            top, bottom, left, right = self.view.crop_bounds()
            if bottom - top > 0 and right - left > 0:
                return (top, bottom, left, right)
        return self._full

    def _refresh(self) -> None:
        top, bottom, left, right = self._current()
        w, h = right - left, bottom - top
        fh, fw = self._full[1], self._full[3]
        removed = 100.0 * (1.0 - (w * h) / float(fw * fh))
        self.size_label.setText(f"{w} × {h}   ({removed:.1f}% removed)")
        # Nothing selected is not an error, but there is nothing to apply either.
        self.apply_btn.setEnabled(self._current() != self._full)

    def _accept(self) -> None:
        b = self._current()
        if b == self._full:
            return
        self._bounds = b
        self.accept()

    def bounds(self) -> tuple[int, int, int, int] | None:
        return self._bounds
