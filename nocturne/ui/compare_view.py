"""Shared before/after compare widget: Off / Wipe / Side by side.

Built as its own widget (not bolted into one dialog) because the app already
had two separate before/after idioms — main-window Before/After and Star
Spikes' wipe divider — and a third one-off inside Starless Levels would be the
same "inconsistent layout" complaint that motivated this file. See
`.superpowers/sdd/2026-09-09-starless-levels/round2-task-A-brief.md`.

Andreas' request: "if the user PTZ's the view both views needs to follow" —
his reference is Photoshop's side-by-side, where pan/zoom is ONE action that
moves both panes at once. That is the one hard requirement here: Off and Wipe
show a single pane, but Side by side's two panes must share one pan/zoom
model, never two that can drift apart.

Reuse, not reinvention:
  - `_ZoomPreview` (curves_dialog.py) already does wheel-zoom, drag-pan and
    visible-region math; imported privately, same as starless_levels_dialog.py
    already does. NOT promoted out of curves_dialog.py — see ruling 1.2 in the
    brief.
  - `ImageView.set_compare()` (image_view.py) already IS the wipe divider —
    zoom-aware grab band, knob, clip mask. Wipe mode uses ImageView as-is
    rather than re-deriving that geometry.

The two mechanisms don't share a coordinate model, so they are not bridged
live: while Wipe is showing, ImageView owns its own pan/zoom (as it already
does everywhere else it is embedded), and CompareView's zoom/pan surface
(`zoom_level` / `set_zoom` / `reset_view` / `visible_rect`) tracks Off/Side's
shared `_ZoomPreview` state regardless of which mode is active. The one
guarantee this file exists to make is about the two SIDE panes, which is where
independent state would actually be invisible drift rather than an accepted
difference between two distinct viewing modes.

The widget only displays what it is given — `set_images()` takes finished
QImages. Cropping a large image to the visible region for performance (as
curves_dialog._render does) is the host's job: `visible_rect()`/`zoom_level()`
are exposed so a host can do that and hand back new images on `viewChanged`.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .curves_dialog import _ZoomPreview, _fitted_size
from .image_view import ImageView

MODES = ("off", "wipe", "side")

# Slack left inside the wipe pane, in pixels — see `CompareView.pane_size`.
_WIPE_MARGIN = 8


def _scaled_pixmap(qimage, box: QSize) -> QPixmap:
    """QImage -> QPixmap fitted into `box`, aspect kept.

    Reuses `_fitted_size` rather than re-deriving the KeepAspectRatio maths
    `curves_dialog._pixmap_for` already got right (that helper takes an
    AstroImage; CompareView is only ever handed a finished QImage, so this is
    the same target-size question asked directly).
    """
    pm = QPixmap.fromImage(qimage)
    if pm.isNull():
        return pm
    target = _fitted_size(pm.width(), pm.height(), box)
    return pm.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


class CompareView(QWidget):
    """Before/after display with three modes, one shared pan/zoom.

    `_after_pane` is the canonical zoom/pan model: it exists in every mode
    (shown alone in Off, alongside `_before_pane` in Side) so it is never
    recreated and never loses state on a mode switch. `_before_pane` is kept
    equal to it on every interaction — see `_on_pane_changed` — rather than
    the two ever being read independently.
    """

    viewChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = "off"
        self._before_img = None
        self._after_img = None
        # Sentinel, not None: None is a legitimate "before" image (clears the
        # wipe divider), so it must still be distinguishable from "never set".
        self._wipe_compare_img = object()

        self._after_pane = _ZoomPreview()
        self._before_pane = _ZoomPreview()
        for pane in (self._after_pane, self._before_pane):
            pane.setMinimumSize(120, 120)
            pane.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._after_pane.viewChanged.connect(lambda: self._on_pane_changed(self._after_pane))
        self._before_pane.viewChanged.connect(lambda: self._on_pane_changed(self._before_pane))

        self._before_label = QLabel("Before")
        self._after_label = QLabel("After")
        for lbl in (self._before_label, self._after_label):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._wipe_view = ImageView()
        # The annotation toggle and the plate-solve object list belong to the
        # main viewer this class was lifted out of, not to a before/after
        # compare pane — CLAUDE.md's rule that a shared widget's behaviour
        # must be opt-in, not on by default, applies to this borrowed chrome
        # too. Zoom pill and the pixel readout stay: pan/zoom affordance and a
        # value readout are both useful here.
        self._wipe_view.annotation_pill.hide()
        self._wipe_view.object_panel.hide()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._rebuild()

    # --- mode ---
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown CompareView mode: {mode!r}")
        if mode == self._mode:
            return
        self._mode = mode
        self._rebuild()

    def _rebuild(self) -> None:
        """Re-lay-out for the current mode, reparenting the persistent panes
        rather than recreating them, so their state (and the wipe divider's
        pixmaps) survive a mode switch.

        The panes are detached BEFORE the old wrapper widgets (the "side"
        mode's before/after boxes) are discarded. Qt owns children through
        their parent: deleting a leftover wrapper while a pane is still
        parented under it would take the pane down too, silently destroying
        state this class exists to keep alive.
        """
        for w in (self._after_pane, self._before_pane,
                 self._before_label, self._after_label, self._wipe_view):
            w.setParent(None)
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if self._mode == "off":
            self._layout.addWidget(self._after_pane, 1)
        elif self._mode == "wipe":
            self._layout.addWidget(self._wipe_view, 1)
        else:  # "side"
            row = QHBoxLayout()
            before_box, after_box = QWidget(), QWidget()
            bv = QVBoxLayout(before_box)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.addWidget(self._before_label)
            bv.addWidget(self._before_pane, 1)
            av = QVBoxLayout(after_box)
            av.setContentsMargins(0, 0, 0, 0)
            av.addWidget(self._after_label)
            av.addWidget(self._after_pane, 1)
            row.addWidget(before_box)
            row.addWidget(after_box)
            container = QWidget()
            container.setLayout(row)
            self._layout.addWidget(container, 1)

        self._render()

    # --- images ---
    def set_images(self, before, after) -> None:
        self._before_img = before
        self._after_img = after
        self._render()

    def _render(self) -> None:
        if self._mode == "off":
            self._apply_pane(self._after_pane, self._after_img)
        elif self._mode == "side":
            self._apply_pane(self._before_pane, self._before_img)
            self._apply_pane(self._after_pane, self._after_img)
        else:  # "wipe"
            if self._after_img is not None:
                self._wipe_view.set_image(self._after_img)
            # set_compare() re-centres the divider, so it is only called when
            # the before image actually changes — never on every render, or
            # a live-updating "after" preview would drag the handle back to
            # the middle on each tick (see star_spikes_dialog._on_compare_toggled).
            if self._before_img is not self._wipe_compare_img:
                self._wipe_view.set_compare(self._before_img)
                self._wipe_compare_img = self._before_img

    def _apply_pane(self, pane: _ZoomPreview, qimage) -> None:
        if qimage is None:
            pane.setPixmap(QPixmap())
            pane.setText("No image")
            return
        pane.setText("")
        pane.setPixmap(_scaled_pixmap(qimage, pane.size()))

    # --- shared pan/zoom model ---
    def _on_pane_changed(self, source: _ZoomPreview) -> None:
        """The whole point of this file: whichever pane the user just touched,
        copy its state onto the other one so they can never read differently."""
        target = self._before_pane if source is self._after_pane else self._after_pane
        target.blockSignals(True)
        target._centre = list(source._centre)
        target.set_zoom(source.zoom_level())
        target.blockSignals(False)
        self.viewChanged.emit()

    def zoom_level(self) -> float:
        return self._after_pane.zoom_level()

    def set_zoom(self, zoom: float) -> None:
        self._after_pane.set_zoom(zoom)

    def reset_view(self) -> None:
        self._after_pane.reset_view()

    def visible_rect(self, shape) -> tuple:
        return self._after_pane.visible_rect(shape)

    def pane_size(self) -> QSize:
        """The box the "after" image is actually DISPLAYED in — not the widget.

        A host that must produce its pixels AT the display size asks this rather
        than `size()`: in Side mode the pane is roughly half the width, and
        rendering to the full width would be rescaled afterwards. Starless
        Levels' clipping overlay is the case that cares — its block-max keeps an
        isolated blown pixel at full intensity and any later rescale re-dilutes
        it.

        Wipe is the exception: `ImageView` fits with `fitInView`, which insets
        the viewport by 2 px and transforms the pixmap nearest-neighbour, so a
        picture sized to the exact viewport is shrunk very slightly — and a
        nearest-neighbour shrink DROPS an isolated speck. Leaving a margin means
        it can only ever scale up, where nearest-neighbour enlarges the speck
        instead.
        """
        if self._mode == "wipe":
            s = self._wipe_view.viewport().size()
            return QSize(max(1, s.width() - _WIPE_MARGIN),
                         max(1, s.height() - _WIPE_MARGIN))
        return self._after_pane.size()

    # --- layout ---
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()
