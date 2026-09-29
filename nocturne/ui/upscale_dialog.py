from __future__ import annotations

import os

import numpy as np

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..core.export import save_jpeg, save_png, save_tiff
from ..core.share import ASPECTS
from ..core.tasks import CancelToken, Cancelled
from ..core.upscale import (
    TIGHTEN_DEFAULT, UPSCALE_MAX_MP, LanczosEngine, finish_upscale, megapixels,
    output_size, prepare_upscale, to_uint8, upscale_filename, upscale_provenance_text,
)
from ..settings import start_dir
from .image_view import ImageView
from .linked_views import copy_view, link_views
from .upscale_navigator import UpscaleNavigator
from .worker import run_async
from . import file_dialogs, theme

# finish_upscale (reduce_stars + recombine) measured 2026-09-29 on his M31 mosaic
# crops: 0.3 s at the 20 MP ceiling (0.5 s at 33 MP, 2.1 s at 150 MP). Half of
# 0.3 s is 150 ms, which is the 150 ms floor.
TIGHTEN_DEBOUNCE_MS = 150

SCALE = 2   # fixed in v1

NOISE_NOTE = ("Noise Reduction hasn't been applied — enlarging makes noise twice as "
              "visible. Worth running it first.")


def _qimage_from_float(data: np.ndarray) -> QImage:
    """8-bit QImage for previewing a float32 [0,1] AstroImage array. Preview
    only — the real upscale + export always operate on the full float data,
    never this 8-bit copy."""
    return _qimage_from_uint8(to_uint8(data))


def _qimage_from_uint8(arr8: np.ndarray) -> QImage:
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
        self._save_runner = _dispatch_save   # injectable for tests
        self._pool = QThreadPool.globalInstance()

        self.picker = ImageView()
        self.picker.setMinimumSize(360, 320)
        self.picker.set_image(_qimage_from_float(self._img.data))
        self.picker.set_crop_overlay(True, aspect_ratio=None)
        self.picker.cropBoxChanged.connect(lambda *_: self._sync_size())

        self.shape_buttons, group = {}, QButtonGroup(self)
        shapes = QHBoxLayout()
        for label, ratio in ASPECTS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, r=ratio: self._set_shape(r))
            group.addButton(b)
            shapes.addWidget(b)
            self.shape_buttons[label] = b
        self.shape_buttons["Original"].setChecked(True)

        self.size_label = QLabel("")
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

        self.plain_view, self.result_view, self.wipe_view = ImageView(), ImageView(), ImageView()
        for v in (self.plain_view, self.result_view, self.wipe_view):
            v.setMinimumSize(240, 220)
        self._pair = QWidget(); pl = QHBoxLayout(self._pair); pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(_labelled("Plain resize", self.plain_view), 1)
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
        self.navigator.set_frame(_qimage_from_float(self._img.data))
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
        cside = QWidget(); cside.setLayout(self._compare_panel); cside.setFixedWidth(240)
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
        root.addWidget(self.status)
        root.addLayout(buttons)
        self._sync_size()

    # --- shape / size ---
    def _set_shape(self, ratio) -> None:
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
        over = mp > UPSCALE_MAX_MP
        self.size_label.setStyleSheet(f"color: {theme.WARNING};" if over else "")
        self.upscale_btn.setEnabled(not over and not self._busy)
        if over:
            self.status.setText(f"Too large to enlarge: {mp:.0f} MP (limit {UPSCALE_MAX_MP} MP). "
                                "Choose a smaller crop.")
        elif self.status.text().startswith("Too large"):
            self.status.setText("")

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
        self._token = CancelToken()
        self._set_busy(True)
        self.status.setText("Separating stars and enlarging…")

        def done(layers) -> None:
            self._token = None
            self._set_busy(False)
            self._layers = layers
            self._show_result()

        def failed(exc) -> None:
            self._token = None
            self._set_busy(False)
            self.status.setText("Cancelled." if isinstance(exc, Cancelled) else f"Failed: {exc}")

        run_async(self._pool, lambda: prepare_upscale(self._img, crop, engine, scale=scale, rc=rc),
                  done, failed, on_progress=self._on_progress, token=self._token)

    def _on_progress(self, done: int, total: int) -> None:
        self.status.setText(f"Separating stars… {done}%")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.cancel_btn.setVisible(busy)
        self._sync_size()

    # --- state 2 ---
    def _show_result(self) -> None:
        self._result = finish_upscale(self._layers, self._tighten)
        plain = _qimage_from_uint8(self._layers.plain_up)
        nocturne = _qimage_from_float(self._result.data)
        if self._unlink is not None:
            self._unlink()
        self.plain_view.set_image(plain)
        self.result_view.set_image(nocturne)
        self.wipe_view.set_image(nocturne)
        self.wipe_view.set_compare(plain)          # plain under the divider's left side
        self._unlink = link_views(self.plain_view, self.result_view)
        self.pages.setCurrentIndex(1)
        h, w = self._result.data.shape[:2]
        self.navigator.set_crop(self._layers.crop, self._scale)
        self.result_view.actual_size()
        self._centre_views(w / 2, h / 2)
        copy_view(self.result_view, self.wipe_view)  # a fresh wipe view opens at the same 100%
        self.views.setCurrentIndex(1 if self.mode_wipe.isChecked() else 0)
        self._sync_navigator()
        self.result_size.setText(f"{w} × {h}")
        self.status.setText(f"Upscaled to {w}×{h}.")
        self._export_btn.setEnabled(True)
        self._open_copy_btn.setEnabled(True)

    def _on_tighten(self, value: int) -> None:
        self._tighten = value / 100.0
        self._tighten_timer.start()

    def _rerender(self) -> None:
        if self._layers is None:
            return
        layers, t = self._layers, self._tighten

        def done(result) -> None:
            if layers is self._layers and t == self._tighten:     # latest wins
                self._result = result
                q = _qimage_from_float(result.data)
                self.result_view.set_image(q)      # same size: zoom/pan stay, linked views stay put
                self.wipe_view.set_image(q)
        run_async(self._pool, lambda: finish_upscale(layers, t), done)

    def _current_result(self):
        """The result at the slider's value NOW — an export never waits on, or
        misses, a re-render still in the debounce (WYSIWYG)."""
        r = self._result
        if r is None or r.metadata["upscale"]["tighten"] != self._tighten:
            self._result = r = finish_upscale(self._layers, self._tighten)
        return r

    def _set_mode(self, wipe: bool) -> None:
        src, dst = (self.result_view, self.wipe_view) if wipe else (self.wipe_view, self.result_view)
        if self.pages.currentIndex() == 1:
            copy_view(src, dst)
        self.views.setCurrentIndex(1 if wipe else 0)
        self._sync_navigator()

    def _centre_views(self, x: float, y: float) -> None:
        for v in (self.result_view, self.wipe_view):
            v.centerOn(x, y)

    def _sync_navigator(self) -> None:
        v = self.wipe_view if self.views.currentIndex() == 1 else self.result_view
        r = v.mapToScene(v.viewport().rect()).boundingRect()
        self.navigator.set_visible_rect(r.x(), r.y(), r.width(), r.height())

    def _change_crop(self) -> None:
        if self._unlink is not None:
            self._unlink(); self._unlink = None
        self._tighten_timer.stop()
        self._layers = self._result = None
        self._export_btn.setEnabled(False); self._open_copy_btn.setEnabled(False)
        self.pages.setCurrentIndex(0)
        self.status.setText("")
        self._sync_size()

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
