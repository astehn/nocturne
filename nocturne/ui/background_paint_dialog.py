"""Paint where the sky is, and where the nebula is, for the Background step.

The October spike (docs/BUILT_IN_BGE_SPIKE_2026-10-21.md) found that fitting a
background is easy and choosing the sky is the whole problem, so the user
chooses it: Sky and Nebula brushes, and an Erase that removes their own paint.
Unpainted areas are left to the automatic selection, which Auto-mask only SHOWS
— the option stores the strokes and nothing else.

Layout is the mockup Andreas approved 2026-11-14 ("exactly how i think it
should work"): tools on the left, the picture on the right, Preview result /
Cancel / Apply bottom right.

Preview result runs the Background step's own painted route on the
full-resolution base, from `option()` — the very dict Apply hands back — so
what it shows is what the step will produce.
"""
from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDialog,
                               QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from ..core.image import AstroImage
from ..core.tasks import CancelToken
from ..steps.background import _AMOUNT, normalise_painted
from .curves_dialog import _ZoomPreview, _downscale, _fit_to_screen, _scaled_to_box
from .preview import qimage_to_rgb8, to_qimage
from .worker import run_async
from .zoom_row import ZoomRow

_PREFERRED = (1180, 760)
_VIEW_MIN = (420, 320)

# The mockup's colours. Painted strokes at ~45% alpha; the Auto-mask layer the
# same hues at ~20%, underneath, so the user's own paint always reads on top.
_SKY_RGB = (0x3f, 0x8f, 0xe0)
_NEBULA_RGB = (0xe0, 0x70, 0x4a)
_PAINT_ALPHA = 115
_AUTO_ALPHA = 51

# Brush size in SCREEN pixels, so a brush feels the same at any zoom; the
# stroke records it in image pixels. 28 is the mockup's default.
_BRUSH_MIN, _BRUSH_MAX, _BRUSH_DEFAULT = 2, 200, 28


# ------------------------------------------------------------ display stretch
def _stretch_params(data: np.ndarray):
    """The linked display stretch (stretch version 3) measured ONCE on the
    linear base. The result view reuses these numbers rather than measuring
    itself: a stretch re-measured on the corrected image would re-level the
    sky and hide the very change the user is checking."""
    from ..core import autostretch as a
    if a.STRETCH_VERSION != a.STRETCH_V3:
        raise NotImplementedError("the paint editor's display follows stretch version 3")
    d = np.asarray(data, np.float32)
    if d.ndim == 2:
        shadow, m = a._v3_channel_params(d, a._TARGET_BG)
        return None, shadow, m
    meds, ref, shadow, m, _mask = a.stretch_v3_params(d, a._TARGET_BG)
    return (np.asarray(meds, np.float32) - np.float32(ref)), shadow, m


def _stretched(data: np.ndarray, params) -> np.ndarray:
    from ..core import autostretch as a
    shift, shadow, m = params
    d = np.asarray(data, np.float32)
    if shift is None:
        return np.clip(a._apply_params(d, shadow, m), 0.0, 1.0)
    with np.errstate(invalid="ignore"):
        out = a._apply_params(d - shift, shadow, m)
        out[~(d.max(axis=2) > a._DATA_EPS)] = 0.0
    return np.clip(out, 0.0, 1.0)


def _pixmap_rgb8(pm: QPixmap) -> np.ndarray:
    return qimage_to_rgb8(pm.toImage())


# ------------------------------------------------------------ the paint view
class _PaintPreview(_ZoomPreview):
    """`_ZoomPreview` whose left drag paints. Space held turns the drag back
    into a pan (the mockup's "pan: drag with space held"); wheel and pinch
    keep zooming and panning as before."""

    strokeChanged = Signal()       # a point was added to the live stroke
    strokeFinished = Signal(dict)  # the completed stroke, in image pixels

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.brush = "sky"
        self.brush_px = _BRUSH_DEFAULT
        self.live = None           # the stroke being drawn
        self._space = False
        self._panning = False
        # The mapping the last render used: visible rect in base pixels, and
        # the pixmap's size inside this label.
        self._rect = (0, 0, 1, 1)
        self._pm_size = (1, 1)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_mapping(self, rect, pm_w: int, pm_h: int) -> None:
        self._rect = tuple(rect)
        self._pm_size = (max(1, pm_w), max(1, pm_h))

    def scale(self) -> tuple:
        """Base pixels per pixmap pixel, (x, y)."""
        x0, y0, x1, y1 = self._rect
        return (x1 - x0) / self._pm_size[0], (y1 - y0) / self._pm_size[1]

    def offset(self) -> tuple:
        return ((self.width() - self._pm_size[0]) / 2,
                (self.height() - self._pm_size[1]) / 2)

    def to_image(self, pos) -> tuple:
        sx, sy = self.scale()
        ox, oy = self.offset()
        return (self._rect[0] + (pos.x() - ox) * sx,
                self._rect[1] + (pos.y() - oy) * sy)

    # --- keys: Space held pans
    def enterEvent(self, event) -> None:
        # Space must reach this widget, not a focused tool button it would click.
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().enterEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space = True
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space = False
                if not self._panning:
                    self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    # --- mouse: paint, or pan with Space
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._space:
            self._panning = True
            super().mousePressEvent(event)
            return
        sx, _ = self.scale()
        x, y = self.to_image(event.position())
        self.live = {"kind": self.brush, "radius": float(self.brush_px * sx),
                     "points": [[x, y]]}
        self.strokeChanged.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            super().mouseMoveEvent(event)
            return
        if self.live is None:
            return
        x, y = self.to_image(event.position())
        lx, ly = self.live["points"][-1]
        # Thinned to a quarter of the radius: the step rasterises every segment,
        # and a point per mouse event on a long stroke is thousands of them for
        # no change in the painted shape.
        if (x - lx) ** 2 + (y - ly) ** 2 >= max(1.0, self.live["radius"] / 4) ** 2:
            self.live["points"].append([x, y])
            self.strokeChanged.emit()

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            super().mouseReleaseEvent(event)
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space
                           else Qt.CursorShape.CrossCursor)
            return
        if self.live is None:
            return
        x, y = self.to_image(event.position())
        if [x, y] != self.live["points"][-1]:
            self.live["points"].append([x, y])
        stroke, self.live = self.live, None
        self.strokeFinished.emit(stroke)


# ------------------------------------------------------------ the dialog
class BackgroundPaintDialog(QDialog):
    def __init__(self, base: AstroImage, option: dict | None = None, parent=None,
                 on_apply=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Background")
        self.resize(*_fit_to_screen(*_PREFERRED))
        self._base = base
        self._on_apply = on_apply
        self._pool = QThreadPool.globalInstance()
        self._params = _stretch_params(base.data)
        self._small = _downscale(base)
        seed = normalise_painted(option) if option else None
        self._strokes: list = copy.deepcopy((seed or {}).get("strokes") or [])
        amount = (seed or {}).get("amount", "strong")

        self._auto = None          # full-res labels, while Auto-mask is on
        self._auto_busy = False
        self._auto_dirty = False
        self._auto_gen = 0
        self._result = None        # the AstroImage Preview result shows
        self._result_gen = 0
        self._result_key = None
        self._token = None
        self._busy_cursor = False
        self._img_pm = None        # the stretched picture, before overlays
        self._img_key = None

        # --- tools
        def tool(text, tip=""):
            b = QPushButton(text)
            b.setCheckable(True)
            # Space pans the view; a focused button would be clicked by it.
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if tip:
                b.setToolTip(tip)
            return b

        self.sky_btn = tool("Sky", "Paint where there is only sky — the fit uses it")
        self.nebula_btn = tool("Nebula", "Paint over the object — the fit never uses it")
        self.erase_btn = tool("Erase", "Remove your own paint; the area goes back "
                                       "to being decided automatically")
        self._brushes = QButtonGroup(self)
        for b, kind in ((self.sky_btn, "sky"), (self.nebula_btn, "nebula"),
                        (self.erase_btn, "erase")):
            self._brushes.addButton(b)
            b.clicked.connect(lambda _=False, k=kind: self._set_brush(k))
        self.sky_btn.setChecked(True)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(_BRUSH_MIN, _BRUSH_MAX)
        self.size_slider.setValue(_BRUSH_DEFAULT)
        self.size_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.size_val = QLabel(f"{_BRUSH_DEFAULT} px")
        self.size_slider.valueChanged.connect(self._set_size)

        self.auto_btn = tool("Auto-mask", "Show what is decided automatically "
                                          "wherever you have not painted")
        self.auto_btn.toggled.connect(self._toggle_auto)
        self.clear_btn = QPushButton("Clear all")
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.clicked.connect(self._clear)
        self.show_mask_check = QCheckBox("Show mask")
        self.show_mask_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.show_mask_check.setChecked(True)
        self.show_mask_check.toggled.connect(lambda _v: self._compose())

        self.light_btn = tool("Light", "Remove about half of the modelled gradient")
        self.strong_btn = tool("Strong", "Remove the whole modelled gradient")
        self._amounts = QButtonGroup(self)
        self._amounts.addButton(self.light_btn)
        self._amounts.addButton(self.strong_btn)
        (self.light_btn if amount == "light" else self.strong_btn).setChecked(True)
        self.light_btn.clicked.connect(self._amount_changed)
        self.strong_btn.clicked.connect(self._amount_changed)

        def heading(t):
            h = QLabel(t.upper())
            h.setStyleSheet("color: #888; font-size: 11px; letter-spacing: 1px;")
            return h

        tools = QVBoxLayout()
        tools.addWidget(heading("Brushes"))
        for b in (self.sky_btn, self.nebula_btn, self.erase_btn):
            tools.addWidget(b)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Brush size"))
        size_row.addStretch(1)
        size_row.addWidget(self.size_val)
        tools.addLayout(size_row)
        tools.addWidget(self.size_slider)
        tools.addWidget(heading("Mask"))
        tools.addWidget(self.auto_btn)
        tools.addWidget(self.clear_btn)
        tools.addWidget(self.show_mask_check)
        tools.addWidget(heading("Amount"))
        amt_row = QHBoxLayout()
        amt_row.addWidget(self.light_btn)
        amt_row.addWidget(self.strong_btn)
        tools.addLayout(amt_row)
        legend = QLabel("Unpainted areas: decided automatically.")
        legend.setWordWrap(True)
        tools.addWidget(legend)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        tools.addWidget(self.status)
        tools.addStretch(1)
        tools_w = QWidget()
        tools_w.setLayout(tools)
        tools_w.setFixedWidth(200)

        # --- picture
        self.view = _PaintPreview()
        self.view.setMinimumSize(*_VIEW_MIN)
        self.view.viewChanged.connect(self._render)
        self.view.strokeChanged.connect(self._compose)
        self.view.strokeFinished.connect(self._stroke_done)
        zoom_row = ZoomRow(self.view)
        self.zoom_label = zoom_row.label

        right = QVBoxLayout()
        right.addLayout(zoom_row)
        right.addWidget(self.view, 1)
        right.addWidget(QLabel("Drag to paint · hold Space and drag to pan · "
                               "pinch or scroll to zoom"))

        # --- bottom right
        self.preview_btn = QPushButton("Preview result")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_btn.toggled.connect(self._toggle_preview)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel_btn.clicked.connect(self.reject)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_btn.clicked.connect(self._apply)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self.preview_btn)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.apply_btn)

        row = QHBoxLayout()
        row.addWidget(tools_w)
        right_w = QWidget()
        right_w.setLayout(right)
        row.addWidget(right_w, 1)
        outer = QVBoxLayout(self)
        outer.addLayout(row, 1)
        outer.addLayout(foot)

    # --- the model
    def option(self) -> dict:
        """The painted option, normalised exactly as the step will record it."""
        amount = "light" if self.light_btn.isChecked() else "strong"
        return normalise_painted({"method": "painted", "amount": amount,
                                  "strokes": self._strokes})

    def _showing_result(self) -> bool:
        return self.preview_btn.isChecked() and self._result is not None

    # --- tools
    def _set_brush(self, kind: str) -> None:
        self.view.brush = kind

    def _set_size(self, v: int) -> None:
        self.view.brush_px = v
        self.size_val.setText(f"{v} px")

    def _stroke_done(self, stroke: dict) -> None:
        self._strokes.append(stroke)
        self._edited()

    def _clear(self) -> None:
        self._strokes = []
        self._edited()

    def _amount_changed(self) -> None:
        self._result = None
        if self.preview_btn.isChecked():
            self._start_result()
        self._render()

    def _edited(self) -> None:
        """Strokes changed: both derived views are stale."""
        self._result = None
        if self.auto_btn.isChecked():
            self._start_auto()
        if self.preview_btn.isChecked():
            self._start_result()
        self._render()

    # --- Auto-mask, off the GUI thread
    def _toggle_auto(self, on: bool) -> None:
        self._auto_gen += 1
        self._auto = None
        if on:
            self._start_auto()
        self._compose()

    def _start_auto(self) -> None:
        """auto_labels takes ~0.8 s at 8 MP, so it runs on the pool. One job at
        a time: a stroke ending mid-job marks it dirty and it reruns once,
        rather than queueing a job per stroke."""
        if self._auto_busy:
            self._auto_dirty = True
            return
        from ..core.painted_background import auto_labels, rasterize_strokes
        data, shape = self._base.data, self._base.data.shape[:2]
        strokes = copy.deepcopy(self.option()["strokes"])
        gen = self._auto_gen
        self._auto_busy, self._auto_dirty = True, False

        def job():
            labels = rasterize_strokes(strokes, shape) if strokes else None
            return auto_labels(data, labels)

        run_async(self._pool, job, lambda lab: self._auto_landed(gen, lab, None),
                  lambda exc: self._auto_landed(gen, None, exc))

    def _auto_landed(self, gen, labels, exc) -> None:
        self._auto_busy = False
        if getattr(self, "_closed", False):
            return
        if gen == self._auto_gen and self.auto_btn.isChecked():
            if exc is not None:
                self.status.setText(str(exc))
            else:
                self._auto = labels
                self._compose()
        if self._auto_dirty and self.auto_btn.isChecked():
            self._start_auto()

    # --- Preview result, off the GUI thread
    def _toggle_preview(self, on: bool) -> None:
        if on:
            self._start_result()
        self._render()

    def _start_result(self) -> None:
        from ..core.painted_background import apply_painted
        opt = self.option()
        key = repr(opt)
        if self._result is not None and self._result_key == key:
            return
        self._result = None
        self._result_gen += 1
        gen = self._result_gen
        if self._token is not None:
            self._token.cancel()
        token = self._token = CancelToken()
        base = self._base
        self.status.setText("Working out the result…")
        self._set_busy(True)

        def job():
            out, _model = apply_painted(base, opt.get("strokes"), _AMOUNT[opt["amount"]])
            token.check()
            return out

        run_async(self._pool, job,
                  lambda out: self._result_landed(gen, key, out, None),
                  lambda exc: self._result_landed(gen, key, None, exc),
                  token=token)

    def _result_landed(self, gen, key, out, exc) -> None:
        if gen != self._result_gen:
            return                      # superseded by a later edit
        self._set_busy(False)
        if getattr(self, "_closed", False):
            return
        if exc is not None:
            # "Too little sky left…" is the user's to act on, not a crash.
            self.status.setText(str(exc) if isinstance(exc, ValueError)
                                else f"Could not preview: {exc}")
            self.preview_btn.blockSignals(True)
            self.preview_btn.setChecked(False)
            self.preview_btn.blockSignals(False)
            self._render()
            return
        self.status.setText("")
        self._result, self._result_key = out, key
        self._render()

    def _set_busy(self, on: bool) -> None:
        if on and not self._busy_cursor:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._busy_cursor = True
        elif not on and self._busy_cursor:
            QApplication.restoreOverrideCursor()
            self._busy_cursor = False

    # --- rendering
    def _pixmap_for_image(self, img: AstroImage, rect) -> QPixmap:
        """`img` inside `rect`, under the base's display stretch, fitted to the
        view. At fit the base comes from its cached decimated copy."""
        view = self.view
        x0, y0, x1, y1 = rect
        h, w = img.data.shape[:2]
        if img is self._base and (x0, y0, x1, y1) == (0, 0, w, h):
            src = self._small
        else:
            crop = img.data[y0:y1, x0:x1]
            src = _downscale(AstroImage(crop, is_linear=img.is_linear,
                                        metadata=dict(img.metadata)),
                             max_edge=max(view.width(), view.height()))
        shown = AstroImage(_stretched(src.data, self._params), is_linear=False,
                           metadata={})
        return _scaled_to_box(QPixmap.fromImage(to_qimage(shown)), view.size())

    def _render(self) -> None:
        view = self.view
        rect = view.visible_rect(self._base.data.shape)
        img = self._result if self._showing_result() else self._base
        key = (id(img), rect, view.width(), view.height())
        if key != self._img_key:
            self._img_pm = self._pixmap_for_image(img, rect)
            self._img_key = key
            view.set_mapping(rect, self._img_pm.width(), self._img_pm.height())
        self.zoom_label.setText(f"{view.zoom_level():.1f}x")
        self._compose()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._img_pm is not None:
            self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._render()

    def _compose(self) -> None:
        """Overlays on the cached picture. Cheap — this runs on every mouse
        move of a stroke, and never re-stretches the image."""
        if self._img_pm is None:
            return
        pm = QPixmap(self._img_pm)
        if self.show_mask_check.isChecked():
            p = QPainter(pm)
            if self._auto is not None:
                p.drawImage(0, 0, self._auto_layer(pm.width(), pm.height()))
            strokes = list(self._strokes)
            if self.view.live is not None:
                strokes.append(self.view.live)
            p.drawImage(0, 0, self._stroke_layer(strokes, pm.width(), pm.height()))
            p.end()
        self.view.setPixmap(pm)

    def _auto_layer(self, pw: int, ph: int) -> QImage:
        x0, y0, x1, y1 = self.view._rect
        lab = self._auto
        ys = np.clip((y0 + (np.arange(ph) + 0.5) * (y1 - y0) / ph).astype(int), 0, lab.shape[0] - 1)
        xs = np.clip((x0 + (np.arange(pw) + 0.5) * (x1 - x0) / pw).astype(int), 0, lab.shape[1] - 1)
        sub = lab[np.ix_(ys, xs)]
        from ..core.painted_background import NEBULA, SKY
        rgba = np.zeros((ph, pw, 4), np.uint8)
        rgba[sub == SKY] = (*_SKY_RGB, _AUTO_ALPHA)
        rgba[sub == NEBULA] = (*_NEBULA_RGB, _AUTO_ALPHA)
        rgba = np.ascontiguousarray(rgba)
        return QImage(rgba.data, pw, ph, 4 * pw, QImage.Format.Format_RGBA8888).copy()

    def _stroke_layer(self, strokes, pw: int, ph: int) -> QImage:
        """Strokes painted in order, each REPLACING what is under it — the same
        rule rasterize_strokes applies — so Erase clears and a later Sky over
        Nebula wins."""
        layer = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        x0, y0, x1, y1 = self.view._rect
        sx, sy = (x1 - x0) / pw, (y1 - y0) / ph
        p = QPainter(layer)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for s in strokes:
            pts = [QPointF((x - x0) / sx, (y - y0) / sy) for x, y in s["points"]]
            if not pts:
                continue
            r = float(s["radius"]) / sx
            if s["kind"] == "erase":
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                colour = QColor(0, 0, 0, 255)
            else:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                colour = QColor(*(_SKY_RGB if s["kind"] == "sky" else _NEBULA_RGB),
                                _PAINT_ALPHA)
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            if len(pts) == 1:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(colour)
                p.drawEllipse(QRectF(pts[0].x() - r, pts[0].y() - r, 2 * r, 2 * r))
            else:
                # One path per stroke, so a stroke crossing itself is one flat
                # colour rather than darker where it overlaps.
                pen = QPen(colour, 2 * r, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.strokePath(path, pen)
        p.end()
        return layer

    # --- close
    def _apply(self) -> None:
        opt = self.option()
        self._shutdown()
        if self._on_apply is not None:
            self._on_apply(opt)
        self.accept()

    def reject(self) -> None:
        self._shutdown()
        super().reject()

    def _shutdown(self) -> None:
        """A preview still computing is cancelled and its result dropped when it
        lands; the busy cursor goes now, not when the job ends."""
        self._closed = True
        if self._token is not None:
            self._token.cancel()
        self._result_gen += 1
        self._auto_gen += 1
        self._set_busy(False)

