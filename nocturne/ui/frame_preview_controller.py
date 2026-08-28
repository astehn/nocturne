"""Row selection -> full-res frame preview, shared by Stack and Ha/OIII.

Both dialogs grade the same raw subs with the same code and show them in the
same table shape, so they want the same preview. It lived only in Stack, which
is why Ha/OIII's table sat next to an empty panel. Keeping one copy is also what
stops the two drifting the way the help text did.
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np
from PySide6.QtGui import QImage

from ..core.autostretch import unlinked_stretch
from ..stacking.frames import load_sub
from .worker import run_async

PREVIEW_CACHE_LIMIT = 4   # full-res QImages (~24 MB each) — small LRU


def load_preview_array(path: str) -> np.ndarray:
    """Full-res, cast-neutral RGB array for a sub. Unlinked stretch so the sky
    lands neutral grey whatever the LP/twilight cast; full resolution so 1:1
    zoom shows real star shapes."""
    return unlinked_stretch(load_sub(path).data)


def to_qimage(arr: np.ndarray) -> QImage:
    arr8 = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
    if arr8.ndim == 2:
        arr8 = np.stack([arr8] * 3, axis=2)
    arr8 = np.ascontiguousarray(arr8)
    h, w = arr8.shape[:2]
    return QImage(arr8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class FramePreviewController:
    """Drives a FramePreview from a table row.

    `row_to_path` is the dialog's own lookup, so the controller never needs to
    know how either dialog stores its grading results.
    """

    def __init__(self, preview, pool, row_to_path, loader=None) -> None:
        self.preview = preview
        self._pool = pool
        self._row_to_path = row_to_path
        self.loader = loader if loader is not None else load_preview_array
        self.cache: OrderedDict = OrderedDict()
        self.wanted = ""          # stale-result guard

    def show_row(self, row: int) -> None:
        path = self._row_to_path(row)
        if not path:
            return
        self.wanted = path
        cached = self.cache.get(path)
        if cached is not None:
            self.cache.move_to_end(path)
            self.preview.show_image(cached)
            return
        loader = self.loader

        def work():
            return path, loader(path)

        run_async(self._pool, work, self._on_loaded,
                  lambda exc: self._on_error(path, exc))

    def resync(self, row: int) -> None:
        """Re-grading can repopulate the table without moving the current cell
        (currentCellChanged won't fire), so the preview has to be told."""
        if self._row_to_path(row):
            self.show_row(row)
        else:
            self.clear()

    def clear(self) -> None:
        self.wanted = ""
        self.preview.clear()

    def _on_loaded(self, result) -> None:
        path, arr = result
        image = to_qimage(arr)
        self.cache[path] = image
        self.cache.move_to_end(path)
        while len(self.cache) > PREVIEW_CACHE_LIMIT:
            self.cache.popitem(last=False)
        if path == self.wanted:
            self.preview.show_image(image)

    def _on_error(self, path, exc) -> None:
        if path == self.wanted:
            self.preview.show_message("Preview failed:\ncould not read frame")
