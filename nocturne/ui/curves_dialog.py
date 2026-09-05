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
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core.curves import (CURVE_CHANNELS, CURVE_RANGES, active_curves,
                           apply_curves, curve_key, deepen_sky_points,
                           gentle_s_points, lift_faint_points,
                           normalize_curves, strong_s_points,
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


class _ZoomPreview(QLabel):
    """A preview you can pan and zoom, rendering from the FULL-resolution base.

    A fixed decimated preview cannot serve a mosaic. Andreas' M 31 is 14004 px
    wide, so the old 640 px preview showed it at a 22x reduction and he could
    not see what a curve was doing. Simply raising the cap does not work either:
    the render is a per-pixel LUT and its cost is linear in pixels — measured
    18 ms at 640 px, 114 ms at 1600, 455 ms at 3200 — so a preview large enough
    to be useful makes the curve drag stutter, and at 1600 px it is STILL a 9x
    reduction of this image.

    Rendering only what is visible fixes both at once: the cost is bounded by
    the widget, not the image, so it stays ~40 ms at any zoom, and at 1:1 the
    pixels are the real ones.
    """

    viewChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        self._zoom = 1.0                  # 1.0 = the whole image fits
        self._centre = [0.5, 0.5]         # in normalised image coords
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def zoom_level(self) -> float:
        return self._zoom

    def reset_view(self) -> None:
        self._zoom, self._centre = 1.0, [0.5, 0.5]
        self.viewChanged.emit()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(1.0, min(64.0, float(zoom)))
        self._clamp()
        self.viewChanged.emit()

    def visible_rect(self, shape) -> tuple:
        """(x0, y0, x1, y1) of the base image currently on screen."""
        h, w = shape[:2]
        ww, wh = max(1, self.width()), max(1, self.height())
        # base pixels per widget pixel, at fit then scaled by the zoom
        s = max(w / ww, h / wh) / self._zoom
        vw, vh = min(w, ww * s), min(h, wh * s)
        cx, cy = self._centre[0] * w, self._centre[1] * h
        x0 = min(max(0.0, cx - vw / 2), max(0.0, w - vw))
        y0 = min(max(0.0, cy - vh / 2), max(0.0, h - vh))
        return int(x0), int(y0), int(round(x0 + vw)), int(round(y0 + vh))

    def _clamp(self) -> None:
        self._centre = [min(1.0, max(0.0, c)) for c in self._centre]

    def wheelEvent(self, event) -> None:
        step = 1.0015 ** event.angleDelta().y()
        self.set_zoom(self._zoom * step)

    def mousePressEvent(self, event) -> None:
        self._drag = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        pos = event.position()
        dx, dy = pos.x() - self._drag.x(), pos.y() - self._drag.y()
        self._drag = pos
        # A drag moves the PICTURE with the pointer, so the view centre moves
        # the other way. Scaled by the visible fraction, so a drag covers the
        # same screen distance whatever the zoom.
        self._centre[0] -= dx / max(1, self.width()) / self._zoom
        self._centre[1] -= dy / max(1, self.height()) / self._zoom
        self._clamp()
        self.viewChanged.emit()


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

    _CHANNEL_LABELS = {"rgb": "RGB", "r": "R", "g": "G", "b": "B", "s": "S"}
    _IDENTITY = [(0.0, 0.0), (1.0, 1.0)]

    def __init__(self, base: AstroImage, points=None, parent=None,
                 on_apply=None, curves=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Curves")
        self.resize(*_fit_to_screen(*_PREFERRED))
        self._base = base
        self._small = _downscale(base)
        self._on_apply = on_apply
        # `points` is the old single-curve argument, still accepted so nothing
        # that passes a bare list breaks; `curves` is the matrix.
        self._curves = normalize_curves(curves if curves is not None else points)
        self._channel = "rgb"
        self._target = "all"

        self.editor = CurveEditor()
        self.editor.setMinimumSize(_EDITOR_MIN, _EDITOR_MIN)
        # The data behind the curve. Without it the plot is an unlabelled black
        # box — the inline editor has always shown this (main_window feeds it on
        # rebuild) and the dialog simply never did, which Andreas spotted at
        # once. From the FULL-resolution base, so the shape matches the image
        # rather than a decimated approximation of it.
        self.editor.set_histogram(base.data)
        self.editor.set_points(self._slot_points())
        self.editor.curveChanged.connect(self._on_edited)

        self.preview_label = _ZoomPreview()
        self.preview_label.setMinimumSize(_PREVIEW_MIN_W, _EDITOR_MIN)
        self.preview_label.viewChanged.connect(self._queue_preview)

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

        # The two selectors. A channel and a hue range together pick one slot
        # of the matrix, which is what makes 35 curves reachable without 35
        # controls — see docs/HSL_DESIGN_QUESTION.md.
        self.channel_buttons = {}
        chan_row = QHBoxLayout()
        chan_row.addWidget(QLabel("Channel"))
        # R, G and B carry their own colour: with five look-alike buttons the
        # one that is selected is the only thing telling you which channel you
        # are shaping, and that is a lot of weight for one highlight to carry.
        tint = {"r": "#ff6b6b", "g": "#5ad469", "b": "#5aa9ff"}
        for ch in CURVE_CHANNELS:
            b = QPushButton(self._CHANNEL_LABELS[ch])
            b.setCheckable(True)
            b.setChecked(ch == "rgb")
            if ch in tint:
                b.setStyleSheet(f"QPushButton {{ color: {tint[ch]}; font-weight: 600; }}"
                                f"QPushButton:checked {{ color: #10131a; "
                                f"background: {tint[ch]}; }}")
            b.clicked.connect(lambda _=False, c=ch: self._set_channel(c))
            chan_row.addWidget(b)
            self.channel_buttons[ch] = b

        self.target_box = QComboBox()
        for r in CURVE_RANGES:
            self.target_box.addItem("All colours" if r == "all" else r.capitalize(), r)
        self.target_box.currentIndexChanged.connect(self._set_target)
        tgt_row = QHBoxLayout()
        tgt_row.addWidget(QLabel("Target"))
        tgt_row.addWidget(self.target_box, 1)

        # A matrix this size hides its own state: without this line a curve set
        # on Reds twenty minutes ago is still shaping the picture invisibly.
        self.active_label = QLabel()
        self.active_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        reset_slot = QPushButton("Reset this curve")
        reset_slot.clicked.connect(self._reset_slot)
        reset_all = QPushButton("Reset all curves")
        reset_all.clicked.connect(self._reset_all)
        reset_row = QHBoxLayout()
        reset_row.addWidget(reset_slot)
        reset_row.addWidget(reset_all)
        self.reset_slot_btn, self.reset_all_btn = reset_slot, reset_all

        left = QVBoxLayout()
        left.addWidget(QLabel("Drag the curve. Click to add a point, "
                              "double-click to remove one."))
        left.addWidget(self.editor, 1)
        left.addLayout(chan_row)
        left.addLayout(tgt_row)
        left.addWidget(self.active_label)
        left.addLayout(reset_row)
        left.addLayout(presets)
        # Scroll to zoom, drag to pan — plus explicit buttons, because a
        # trackpad gesture is not discoverable and this is the one surface where
        # a large mosaic is unusable without it.
        self.zoom_label = QLabel("1.0x")
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(self.preview_label.reset_view)
        in_btn = QPushButton("+")
        in_btn.clicked.connect(
            lambda: self.preview_label.set_zoom(self.preview_label.zoom_level() * 1.5))
        out_btn = QPushButton("−")
        out_btn.clicked.connect(
            lambda: self.preview_label.set_zoom(self.preview_label.zoom_level() / 1.5))
        self.fit_btn, self.zoom_in_btn, self.zoom_out_btn = fit_btn, in_btn, out_btn
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Preview"))
        zoom_row.addStretch(1)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(out_btn)
        zoom_row.addWidget(in_btn)
        zoom_row.addWidget(fit_btn)

        right = QVBoxLayout()
        right.addLayout(zoom_row)
        right.addWidget(self.preview_label, 1)
        right.addWidget(QLabel("Scroll to zoom · drag to pan"))

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
        self._refresh_active()
        self._render()

    # --- model ---
    def points(self):
        """The CURRENT slot's points. Kept for callers that only ever wanted the
        one curve; `curves()` is the whole picture."""
        return self.editor.points()

    def curves(self) -> dict:
        """The whole matrix, with the slot being edited folded in."""
        out = dict(self._curves)
        out[self._slot()] = list(self.editor.points())
        return normalize_curves(out)

    def _slot(self) -> str:
        return curve_key(self._channel, self._target)

    def _slot_points(self):
        return self._curves.get(self._slot(), list(self._IDENTITY))

    def compose(self, img: AstroImage | None = None) -> AstroImage:
        """The single path. Preview and Apply both come through here."""
        return apply_curves(img if img is not None else self._base, self.curves())

    # --- interaction ---
    def _on_edited(self, *_):
        """Store the edit into its slot BEFORE previewing. Holding it only in
        the editor would lose it the moment the user changed channel — which is
        the first thing anyone does with two selectors."""
        self._curves[self._slot()] = list(self.editor.points())
        self._refresh_active()
        self._queue_preview()

    def _set_channel(self, channel: str) -> None:
        self._channel = channel
        for ch, b in self.channel_buttons.items():
            b.setChecked(ch == channel)
        self._load_slot()

    def _set_target(self, *_):
        self._target = self.target_box.currentData()
        self._load_slot()

    def _load_slot(self) -> None:
        """Show the selected slot. blockSignals so swapping the displayed curve
        does not register as an edit of the slot just arrived at."""
        self.editor.blockSignals(True)
        self.editor.set_points(self._slot_points())
        self.editor.blockSignals(False)
        self._refresh_active()
        self._queue_preview()

    def _refresh_active(self) -> None:
        names = active_curves(self.curves())
        self.active_label.setText("Active curves: "
                                  + (", ".join(names) if names else "none"))

    def _reset_slot(self) -> None:
        self._curves.pop(self._slot(), None)
        self._load_slot()

    def _reset_all(self) -> None:
        self._curves = {}
        self._load_slot()

    def _queue_preview(self, *_):
        self._timer.start(60)

    def _reset(self):
        self._reset_slot()

    def _preset(self, fn):
        # Presets are measured from the FULL-resolution base, not the decimated
        # preview: they read percentiles of the image, and a decimated copy has
        # slightly different statistics. The curve must be the one that will be
        # committed.
        self.editor.set_points(fn(self._base.data))

    def _render(self):
        """Render only what is on screen, from the FULL-resolution base.

        `_small` is still used at fit, where the whole image is visible and a
        decimated copy is exactly right. Zoomed in, the crop comes from the base
        so the pixels are the real ones — and because the crop is reduced to the
        widget's size first, the cost is bounded by the widget rather than by
        the image.
        """
        view = self.preview_label
        if view.zoom_level() <= 1.0:
            src = self._small
        else:
            x0, y0, x1, y1 = view.visible_rect(self._base.data.shape)
            crop = self._base.data[y0:y1, x0:x1]
            src = _downscale(AstroImage(crop, is_linear=self._base.is_linear,
                                        metadata=dict(self._base.metadata)),
                             max_edge=max(view.width(), view.height()))
        out = self.compose(src)
        self.preview_label.setPixmap(_pixmap_for(out, view.size()))
        self.zoom_label.setText(f"{view.zoom_level():.1f}x")

    def _apply(self):
        if self._on_apply is not None:
            self._on_apply(self.curves())
        self.accept()


def _pixmap_for(img: AstroImage, size):
    from PySide6.QtGui import QPixmap
    pm = QPixmap.fromImage(to_qimage(img))
    return pm.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
