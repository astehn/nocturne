from __future__ import annotations

import os

import numpy as np
import shiboken6

from PySide6.QtCore import QPoint, Qt, QThreadPool, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..core.export import save_jpeg, save_png, save_tiff
from ..core.share import ASPECTS
from ..core.tasks import CancelToken, Cancelled
from ..core.upscale import (
    TIGHTEN_DEFAULT, LanczosEngine, memory_gb, upscale_limit_mp, finish_upscale, megapixels,
    output_size, prepare_upscale, upscale_filename, upscale_provenance_text,
)
from ..settings import start_dir
from .image_view import ImageView
from .linked_views import link_views
from .progress_ring import ProgressRing
from .upscale_navigator import UpscaleNavigator
from .worker import run_async
from . import file_dialogs, theme
from .help_link import HelpLink

# finish_upscale (reduce_stars + recombine) measured 2026-09-29 on his M31 mosaic
# crops: 0.22 s at 20 MP, 0.46 s at 42 MP — the limit on the 16 GB laptops most
# owners have (the limit now follows memory, core/upscale.upscale_limit_mp).
# Half the 42 MP time, rounded: re-rendering far more often than a render lasts
# only queues work the latest-wins guard throws away.
TIGHTEN_DEBOUNCE_MS = 230

SCALE = 2   # fixed in v1

# The navigator is ~240 px wide, so 600 px stays sharp at 2x. A full-resolution
# pixmap costs 4 bytes a pixel for a thumbnail: 80 MB for a 20 MP frame.
NAV_LONG_SIDE = 600

NOISE_NOTE = ("Noise Reduction hasn't been applied — enlarging makes noise twice as "
              "visible. Worth running it first.")


def _qimage_from_float(data: np.ndarray) -> QImage:
    """8-bit QImage for previewing a float32 [0,1] AstroImage array. Preview
    only — the real upscale + export always operate on the full float data,
    never this 8-bit copy."""
    arr8 = (np.clip(data, 0.0, 1.0) * 255).astype(np.uint8)
    if arr8.ndim == 2:
        arr8 = np.stack([arr8] * 3, axis=2)
    arr8 = np.ascontiguousarray(arr8)
    h, w = arr8.shape[:2]
    return QImage(arr8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _labelled(text: str, view) -> QWidget:
    w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(QLabel(text)); lay.addWidget(view, 1)
    return w


def _dispatch_save(img, path: str) -> None:
    """Default `_save_runner`: pick the writer by the export extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tiff", ".tif"):
        save_tiff(img, path)
    elif ext == ".png":
        save_png(img, path)
    else:
        save_jpeg(img, path)


ORIGINAL_TIP = ("Your crop as it is, drawn at the upscale's size — at 100% each original "
                "pixel is a 2×2 block — so you can see what the upscale changes and "
                "whether anything got worse.")
# Wide enough for the navigator to be a map rather than a stamp (his note,
# 2026-09-29: "very very small even though there is plenty of room").
COMPARE_PANEL_W = 300

class UpscaleDialog(QDialog):
    def __init__(self, img, metadata: dict, settings, rc=None, on_open_copy=None, parent=None,
                 *, denoised: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upscale Crop")
        self.setMinimumSize(800, 500)
        self.resize(1000, 640)
        self._img = img
        self._metadata = metadata
        self._settings = settings
        self._rc = rc
        self._on_open_copy = on_open_copy
        self._scale = SCALE
        self._engine = LanczosEngine()
        self._result = None
        self._layers = None
        self._tighten = TIGHTEN_DEFAULT
        self._token = None
        self._busy = False
        self._closed = False
        self._save_runner = _dispatch_save   # injectable for tests
        self._pool = QThreadPool.globalInstance()

        frame = _qimage_from_float(self._img.data)     # once: it is the slow part of opening
        self.picker = ImageView()
        self.picker.setMinimumSize(360, 320)
        self.picker.set_image(frame)
        self.picker.set_crop_overlay(True, aspect_ratio=None)
        self.picker.cropBoxChanged.connect(lambda *_: self._sync_size())
        self.picker.cropBoxShown.connect(self._sync_size)

        # Three rows of two: six in one row of the 240 px panel squeezed every
        # label, and three across still cut "Original" (70 px for an 80 px hint).
        self.shape_buttons, group = {}, QButtonGroup(self)
        shapes = QGridLayout()
        for i, (label, ratio) in enumerate(ASPECTS):
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, r=ratio: self._set_shape(r))
            group.addButton(b)
            shapes.addWidget(b, i // 2, i % 2)
            self.shape_buttons[label] = b
        self.shape_buttons["Original"].setChecked(True)

        self.size_label = QLabel("")
        # The limit follows this computer's memory (core/upscale.py), so the
        # panel says what it is and why, beside the button it disables — in
        # the status line at the foot of the window it went unseen (his test,
        # 2026-09-29: "if i select Original im not allowed to press upscale").
        self._limit_mp = upscale_limit_mp()
        gb = memory_gb()
        self.limit_label = QLabel(
            f"Up to {self._limit_mp} MP on this computer"
            + (f" ({gb} GB of memory)" if gb else ""))
        self.limit_label.setObjectName("stepDesc")
        self.limit_label.setWordWrap(True)
        self.limit_note = QLabel("")
        self.limit_note.setWordWrap(True)
        self.limit_note.setStyleSheet(f"color: {theme.WARNING};")
        self.limit_note.hide()
        self.noise_note = QLabel(NOISE_NOTE)
        self.noise_note.setWordWrap(True)
        self.noise_note.setStyleSheet(f"color: {theme.WARNING};")
        self.noise_note.setVisible(not denoised)
        self.upscale_btn = QPushButton("Upscale 2×")
        self.upscale_btn.setObjectName("primary")
        self.upscale_btn.clicked.connect(self._on_upscale_clicked)

        panel = QVBoxLayout()
        panel.addWidget(QLabel("<b>Shape</b>"))
        panel.addLayout(shapes)
        panel.addWidget(QLabel("<b>Size</b>"))
        panel.addWidget(self.size_label)
        panel.addWidget(self.limit_label)
        panel.addWidget(self.limit_note)
        panel.addWidget(self.noise_note)
        panel.addStretch(1)
        panel.addWidget(self.upscale_btn)
        side = QWidget()
        side.setLayout(panel)
        side.setFixedWidth(240)

        pick = QHBoxLayout()
        pick.addWidget(self.picker, 1)
        pick.addWidget(side)
        pick_page = QWidget()
        pick_page.setLayout(pick)
        self.pages = QStackedWidget()
        self.pages.addWidget(pick_page)

        self.original_view, self.result_view, self.wipe_view = ImageView(), ImageView(), ImageView()
        for v in (self.original_view, self.result_view, self.wipe_view):
            v.setMinimumSize(240, 220)
        self._pair = QWidget(); pl = QHBoxLayout(self._pair); pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(_labelled("Original", self.original_view), 1)
        self.original_view.setToolTip(ORIGINAL_TIP)
        pl.addWidget(_labelled("Nocturne", self.result_view), 1)
        self.views = QStackedWidget(); self.views.addWidget(self._pair); self.views.addWidget(self.wipe_view)

        self.mode_side, self.mode_wipe = QPushButton("Side by side"), QPushButton("Wipe")
        mg = QButtonGroup(self)
        for b in (self.mode_side, self.mode_wipe):
            b.setCheckable(True); mg.addButton(b)
        self.mode_side.setChecked(True)
        self.mode_side.clicked.connect(lambda: self._set_mode(False))
        self.mode_wipe.clicked.connect(lambda: self._set_mode(True))

        self.navigator = UpscaleNavigator()
        small = frame
        if max(frame.width(), frame.height()) > NAV_LONG_SIDE:
            small = frame.scaled(NAV_LONG_SIDE, NAV_LONG_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        self.navigator.set_frame(small, full_size=(frame.width(), frame.height()))
        self.navigator.centreRequested.connect(self._centre_views)
        self.result_size = QLabel("")
        self.change_crop_btn = QPushButton("◀ Change crop")
        self.change_crop_btn.clicked.connect(self._change_crop)
        self._compare_panel = QVBoxLayout()
        for w in (QLabel("<b>Navigator</b>"), self.navigator, self.result_size):
            self._compare_panel.addWidget(w)
        self._compare_panel.addStretch(1); self._compare_panel.addWidget(self.change_crop_btn)
        self.tighten_slider = QSlider(Qt.Orientation.Horizontal)
        self.tighten_slider.setRange(0, 100)
        self.tighten_slider.setValue(round(TIGHTEN_DEFAULT * 100))
        self.tighten_slider.setToolTip("How much smaller and dimmer the stars are drawn in the "
                                       "enlargement. 0 leaves them as they are.")
        self.tighten_slider.valueChanged.connect(self._on_tighten)
        self._tighten_timer = QTimer(self); self._tighten_timer.setSingleShot(True)
        self._tighten_timer.setInterval(TIGHTEN_DEBOUNCE_MS)
        self._tighten_timer.timeout.connect(self._rerender)
        for w in (QLabel("<b>Star tightening</b>"), self.tighten_slider,
                  QLabel("none ··· strong")):
            self._compare_panel.insertWidget(self._compare_panel.count() - 2, w)
        cside = QWidget(); cside.setLayout(self._compare_panel); cside.setFixedWidth(COMPARE_PANEL_W)
        modes = QHBoxLayout(); modes.addStretch(1); modes.addWidget(self.mode_side); modes.addWidget(self.mode_wipe)
        cmp_col = QVBoxLayout(); cmp_col.addLayout(modes); cmp_col.addWidget(self.views, 1)
        cmp = QHBoxLayout(); cmp.addLayout(cmp_col, 1); cmp.addWidget(cside)
        page = QWidget(); page.setLayout(cmp)
        self.pages.addWidget(page)
        self._unlink = None
        for v in (self.result_view, self.wipe_view):
            v.viewChanged.connect(self._sync_navigator)

        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._export_btn.setEnabled(False)
        self._open_copy_btn = QPushButton("Open as copy")
        self._open_copy_btn.clicked.connect(self._do_open_copy)
        self._open_copy_btn.setEnabled(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self._export_btn)
        buttons.addWidget(self._open_copy_btn)
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(lambda: self._token and self._token.cancel())
        buttons.addWidget(self.cancel_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)
        buttons.addWidget(self._close_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.pages, 1)
        self.status_ring = ProgressRing(size="small")
        self.status_ring.hide()
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(self.status_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status, 1)
        root.addLayout(status_row)
        self.help_link = HelpLink("upscale", self)
        root.addWidget(self.help_link, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(buttons)
        self._sync_size()

    # --- shape / size ---
    def _set_shape(self, ratio) -> None:
        # apply_aspect only reshapes a box that exists; a shape picked first was
        # stored and then ignored by the whole-frame box the first click drew.
        if ratio is not None and not self.picker.crop_box_visible():
            self.picker.show_crop_box()
        self.picker.apply_aspect(ratio)
        self._sync_size()

    def _crop_dims(self) -> tuple[int, int]:
        crop = self._current_crop()
        if crop is None:
            h, w = self._img.data.shape[:2]
            return w, h
        top, bottom, left, right = crop
        return right - left, bottom - top

    def _sync_size(self) -> None:
        w, h = self._crop_dims()
        ow, oh = output_size(w, h, self._scale)
        self.size_label.setText(f"{w} × {h} → {ow} × {oh}")
        mp = megapixels(ow, oh)
        over = mp > self._limit_mp
        self.size_label.setStyleSheet(f"color: {theme.WARNING};" if over else "")
        self.upscale_btn.setEnabled(not over and not self._busy)
        self.limit_note.setText(
            f"Too large to enlarge on this computer: {mp:.0f} MP. "
            "Make the crop smaller." if over else "")
        self.limit_note.setVisible(over)

    # --- crop ---
    def _current_crop(self):
        if self.picker.crop_box_visible():
            top, bottom, left, right = self.picker.crop_bounds()
            if bottom - top > 0 and right - left > 0:
                return (top, bottom, left, right)
        return None

    # --- run (synchronous core; the button routes this off-thread) ---
    def _run_upscale(self) -> None:
        self._layers = prepare_upscale(self._img, self._current_crop(), self._engine,
                                       scale=self._scale, rc=self._rc)
        self._show_result()

    def _on_upscale_clicked(self) -> None:
        if self._busy:
            return
        crop, engine, scale, rc = self._current_crop(), self._engine, self._scale, self._rc
        self._token = token = CancelToken()
        self._set_busy(True)
        self.status.setText("Separating stars and enlarging…")
        self.status_ring.set_indeterminate()
        self.status_ring.show()

        def done(layers) -> None:
            if self._gone():
                return
            self._token = None
            self._set_busy(False)
            if token.cancelled:        # work that never checks finishes anyway — drop it
                self.status.setText("Cancelled.")
                return
            self._layers = layers
            self._show_result()

        def failed(exc) -> None:
            if self._gone():
                return
            self._token = None
            self._set_busy(False)
            self.status.setText("Cancelled." if isinstance(exc, Cancelled) else f"Failed: {exc}")

        run_async(self._pool, lambda: prepare_upscale(self._img, crop, engine, scale=scale, rc=rc),
                  done, failed, on_progress=self._on_progress, token=self._token)

    def _on_progress(self, done: int, total: int) -> None:
        if self._gone():
            return
        self.status.setText(f"Separating stars… {done}%")
        self.status_ring.set_progress(done, total)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.cancel_btn.setVisible(busy)
        if not busy:
            self.status_ring.hide()
        self._sync_size()

    # --- state 2 ---
    def _show_result(self) -> None:
        self._result = finish_upscale(self._layers, self._tighten)
        h, w = self._result.data.shape[:2]
        original = self._original_enlarged(w, h)
        nocturne = _qimage_from_float(self._result.data)
        if self._unlink is not None:
            self._unlink()
        self.original_view.set_image(original)
        self.result_view.set_image(nocturne)
        self.wipe_view.set_image(nocturne)
        self.wipe_view.set_compare(original)       # the original under the divider's left side
        self._unlink = link_views(self.original_view, self.result_view)
        self.pages.setCurrentIndex(1)
        self.views.setCurrentIndex(1 if self.mode_wipe.isChecked() else 0)
        self.navigator.set_crop(self._layers.crop, self._scale)
        self.result_view.actual_size()
        self._centre_views(w / 2, h / 2)
        self._carry_view(self.result_view, self.wipe_view)  # a fresh wipe view opens at the same 100%
        self._sync_navigator()
        self.result_size.setText(f"{w} × {h}")
        self.status.setText(f"Upscaled to {w}×{h}.")
        self._export_btn.setEnabled(True)
        self._open_copy_btn.setEnabled(True)

    def _original_enlarged(self, w: int, h: int) -> QImage:
        """The crop as it is, each pixel drawn as a block, at the result's size.

        His question was "does upscaling degrade my picture?" — so the left
        side is the original, not another resize (2026-09-29). Nearest-
        neighbour on purpose: any smoothing here would be a resize of our own
        choosing, and the point is to see the original's real pixels."""
        crop = self._layers.crop
        data = self._img.data if crop is None else self._img.data[crop[0]:crop[1], crop[2]:crop[3]]
        return _qimage_from_float(data).scaled(
            w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)

    def _on_tighten(self, value: int) -> None:
        self._tighten = value / 100.0
        self._tighten_timer.start()

    def _rerender(self) -> None:
        if self._layers is None:
            return
        layers, t = self._layers, self._tighten

        def done(result) -> None:
            if self._gone():
                return
            if layers is self._layers and t == self._tighten:     # latest wins
                self._result = result
                q = _qimage_from_float(result.data)
                self.result_view.set_image(q)      # same size: zoom/pan stay, linked views stay put
                self.wipe_view.set_image(q)
                if self.status.text().startswith("Couldn't update"):
                    h, w = result.data.shape[:2]
                    self.status.setText(f"Upscaled to {w}×{h}.")

        def failed(exc) -> None:
            # Near the ceiling this is usually memory. Say so, and leave the
            # previous picture up rather than a view that silently went stale.
            if self._gone() or layers is not self._layers:
                return
            self.status.setText(f"Couldn't update the preview: {exc}")
        run_async(self._pool, lambda: finish_upscale(layers, t), done, failed)

    def _current_result(self):
        """The result at the slider's value NOW — an export never waits on, or
        misses, a re-render still in the debounce (WYSIWYG)."""
        r = self._result
        if r is None or r.metadata["upscale"]["tighten"] != self._tighten:
            self._result = r = finish_upscale(self._layers, self._tighten)
        return r

    def _set_mode(self, wipe: bool) -> None:
        src, dst = (self.result_view, self.wipe_view) if wipe else (self.wipe_view, self.result_view)
        self.views.setCurrentIndex(1 if wipe else 0)   # first: dst must have its real size
        if self.pages.currentIndex() == 1:
            self._carry_view(src, dst)
        self._sync_navigator()

    @staticmethod
    def _carry_view(src, dst) -> None:
        """Same zoom, same centre. The wipe view is about twice as wide as one of
        the pair, so copying scroll values (copy_view) moved the picture."""
        vp = src.viewport().rect()
        c = src.mapToScene(QPoint(vp.width() // 2, vp.height() // 2))
        dst.setTransform(src.transform())
        dst._fitted = src._fitted
        dst.centerOn(c)
        dst._note_zoom()

    def _centre_views(self, x: float, y: float) -> None:
        for v in (self.result_view, self.wipe_view):
            v.centerOn(x, y)

    def _sync_navigator(self) -> None:
        v = self.wipe_view if self.views.currentIndex() == 1 else self.result_view
        r = v.mapToScene(v.viewport().rect()).boundingRect()
        self.navigator.set_visible_rect(r.x(), r.y(), r.width(), r.height())

    def _change_crop(self) -> None:
        self._tighten_timer.stop()
        self._clear_views()                # ~320 MB of pixmaps at 20 MP, hidden
        self._layers = self._result = None
        self._export_btn.setEnabled(False); self._open_copy_btn.setEnabled(False)
        self.pages.setCurrentIndex(0)
        self.status.setText("")
        self._sync_size()

    def _clear_views(self) -> None:
        if self._unlink is not None:
            self._unlink(); self._unlink = None
        for v in (self.original_view, self.result_view, self.wipe_view):
            v.set_compare(None)
            v.set_image(QImage())

    # --- lifetime ---
    def _gone(self) -> bool:
        """A worker's signals outlive the dialog; its callbacks must not build
        on a closed dialog, or touch one whose C++ side is deleted."""
        return not shiboken6.isValid(self) or self._closed

    def done(self, r: int) -> None:
        """Every way out (Close, Esc, the title bar, Open as copy) comes here.
        Stop the work and let go of the layers, result and pixmaps — the dialog
        held ~1.3 GB at 20 MP, and closing mid-run left StarNet2 running."""
        self._closed = True
        if self._token is not None:
            self._token.cancel()
            self._token = None
        self._busy = False
        self._tighten_timer.stop()
        self._clear_views()
        self.navigator.set_frame(QImage())
        self._layers = self._result = None
        super().done(r)

    # --- export / open as copy ---
    def _on_export_clicked(self) -> None:
        if self._result is None:
            return
        default_name = upscale_filename(self._metadata.get("source_label"), self._scale)
        default_path = os.path.join(start_dir(self._settings.base_dir), default_name)
        path, _ = file_dialogs.save_file(self, "Export upscaled image", default_path,
                                              "JPEG (*.jpg);;PNG (*.png);;TIFF (*.tiff)")
        if path:
            self._do_export(path)

    def _do_export(self, path: str) -> None:
        if self._result is None:
            return
        result = self._current_result()
        self._save_runner(result, path)
        stem = os.path.splitext(path)[0]
        with open(stem + ".txt", "w") as f:
            f.write(upscale_provenance_text(result.metadata))
        self.status.setText(f"Saved {os.path.basename(path)}")

    def _do_open_copy(self) -> None:
        """`on_open_copy` returns False if it declined to swap — it asks first
        when the open project has unsaved edits. Anything else (including the
        None a caller that never declines returns) counts as opened."""
        if self._result is not None and self._on_open_copy is not None:
            if self._on_open_copy(self._current_result()) is False:
                return         # they kept their project; leave the dialog up
            self.accept()      # close so the user lands on the main window showing the copy
                               # (the swap was invisible behind the modal dialog, esp. full screen)
