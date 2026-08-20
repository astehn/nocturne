"""A large curves editor, for when the inline one is too small to work in.

Measured in Andreas' own configuration, the inline editor is 336 x 240 — and
drawn STRETCHED, because it fills its widget rather than staying square, so the
identity line is not at 45 degrees and a horizontal drag moves 1.4x further per
pixel than a vertical one. At 1.31 px per 8-bit level, a one-pixel slip is
three quarters of a level. His words: "small and fiddly ... difficult to see and
control what you are actually doing."

The right pane is a FIXED 400 px (see main_window.RIGHT_PANE_W, which exists so
the image never moves between steps), so the inline editor cannot simply be made
wider. This dialog is the answer to that, following Colour Balance and
Narrowband: a big working area with a live preview beside it.

The inline editor stays as the default surface — a quick tweak should not need
a window.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core.curves import (apply_curve, deepen_sky_points, gentle_s_points,
                           lift_faint_points, strong_s_points,
                           tame_highlights_points)
from ..core.image import AstroImage
from .curve_editor import CurveEditor
from .preview import to_qimage

_PREVIEW_MAX = 640

# Small enough that the whole dialog fits a 1280 x 800 laptop — roughly
# 1280 x 750 usable after the menu bar — and still clearly bigger than the
# inline plot's 304 px square, or there is no reason to open it. The first
# version used 560 and gave the dialog a MINIMUM of 1118 x 768: taller than the
# screen, so on an Air it could not even be resized to fit. Andreas raised the
# small-screen case while this was being built; it would otherwise have been
# found on the Air, which is the machine nobody currently has to test on.
_EDITOR_MIN = 360
_PREVIEW_MIN_W = 280

# What it opens at when there is room. Clamped to the screen below.
_PREFERRED = (1180, 760)

# The presets, in the order they are offered. Each takes the image and returns
# control points measured from it — never fixed positions. See core.curves.
PRESETS = (
    ("Add contrast", gentle_s_points),
    ("Stronger contrast", strong_s_points),
    ("Lift faint detail", lift_faint_points),
    ("Deepen sky", deepen_sky_points),
    ("Tame highlights", tame_highlights_points),
)


def _fit_to_screen(w: int, h: int) -> tuple:
    """Never open larger than the display.

    A dialog taller than the screen puts its buttons off the bottom edge, which
    is where the primary action lives. Leaves a margin for the menu bar and dock
    rather than assuming the reported available area already excludes them.
    """
    screen = QApplication.primaryScreen()
    if screen is None:
        return w, h
    avail = screen.availableGeometry()
    return (min(w, max(640, avail.width() - 40)),
            min(h, max(480, avail.height() - 60)))


def _downscale(img: AstroImage, max_edge: int = _PREVIEW_MAX) -> AstroImage:
    """Area-average, never stride.

    Taking every Nth pixel throws stars away: measured on three hundred
    synthetic stars, a strided preview lost two hundred and fifty-three of them
    and drew the survivors at full brightness. Averaging keeps every one.
    """
    from skimage.transform import downscale_local_mean
    h, w = img.data.shape[:2]
    step = max(1, max(h, w) // max_edge)
    if step == 1:
        return img
    blocks = (step, step, 1) if img.data.ndim == 3 else (step, step)
    small = downscale_local_mean(img.data, blocks).astype(np.float32)
    return AstroImage(np.ascontiguousarray(small),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


class CurvesDialog(QDialog):
    """Edit the tone curve at a size you can actually aim in.

    `compose()` is the ONE path used for both the preview and the committed
    result, so what is on screen is what Apply produces. The preview runs on a
    decimated copy purely for speed; a curve is a per-pixel lookup, so the
    mapping is identical at any resolution.
    """

    def __init__(self, base: AstroImage, points=None, parent=None,
                 on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Curves")
        self.resize(*_fit_to_screen(*_PREFERRED))
        self._base = base
        self._small = _downscale(base)
        self._on_apply = on_apply

        self.editor = CurveEditor()
        self.editor.setMinimumSize(_EDITOR_MIN, _EDITOR_MIN)
        if points:
            self.editor.set_points(points)
        self.editor.curveChanged.connect(self._queue_preview)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(_PREVIEW_MIN_W, _EDITOR_MIN)

        presets = QGridLayout()
        self.preset_buttons = {}
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset)
        presets.addWidget(reset, 0, 0)
        self.reset_btn = reset
        for i, (label, fn) in enumerate(PRESETS, start=1):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=fn: self._preset(f))
            presets.addWidget(b, i // 3, i % 3)
            self.preset_buttons[label] = b

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)

        left = QVBoxLayout()
        left.addWidget(QLabel("Drag the curve. Click to add a point, "
                              "double-click to remove one."))
        left.addWidget(self.editor, 1)
        left.addLayout(presets)
        right = QVBoxLayout()
        right.addWidget(QLabel("Preview"))
        right.addWidget(self.preview_label, 1)

        row = QHBoxLayout()
        lw, rw = QWidget(), QWidget()
        lw.setLayout(left); rw.setLayout(right)
        row.addWidget(lw, 3)
        row.addWidget(rw, 2)

        outer = QVBoxLayout(self)
        outer.addLayout(row, 1)
        outer.addWidget(buttons)

        # Debounced like the other live previews: a curve drag emits on every
        # mouse move, and re-rendering per event makes the drag stutter.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render)
        self._render()

    # --- model ---
    def points(self):
        return self.editor.points()

    def compose(self, img: AstroImage | None = None) -> AstroImage:
        """The single path. Preview and Apply both come through here."""
        return apply_curve(img if img is not None else self._base, self.points())

    # --- interaction ---
    def _queue_preview(self, *_):
        self._timer.start(60)

    def _reset(self):
        self.editor.set_points([(0.0, 0.0), (1.0, 1.0)])

    def _preset(self, fn):
        # Presets are measured from the FULL-resolution base, not the decimated
        # preview: they read percentiles of the image, and a decimated copy has
        # slightly different statistics. The curve must be the one that will be
        # committed.
        self.editor.set_points(fn(self._base.data))

    def _render(self):
        out = self.compose(self._small)
        self.preview_label.setPixmap(_pixmap_for(out, self.preview_label.size()))

    def _apply(self):
        if self._on_apply is not None:
            self._on_apply(self.points())
        self.accept()


def _pixmap_for(img: AstroImage, size):
    from PySide6.QtGui import QPixmap
    pm = QPixmap.fromImage(to_qimage(img))
    return pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
