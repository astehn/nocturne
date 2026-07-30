from __future__ import annotations

import numpy as np

from .image import AstroImage


def _counts_256(channel: np.ndarray) -> np.ndarray:
    """256 bins straight off the uint8 quantisation the canvas already uses, so
    bin 255 means exactly 'displays as pure white' — the same test the clipping
    overlay applies. ~4x faster than np.histogram over float32.

    Non-finite values (NaN is reachable via fits_io._normalize(), which leaves
    the array untouched when arr.max() is NaN, since AstroImage enforces no
    finiteness invariant) are replaced with 0.0 before the cast, deliberately:
    the naive `(nan * 255 + 0.5).astype(np.uint8)` also produces 0, but raises
    a RuntimeWarning on every canvas update. Landing NaN in bin 0 matches
    nocturne.ui.preview.to_qimage's non-linear (post-Stretch) branch, whose own
    uint8 cast already implicitly turns NaN into displayed black — so for
    non-linear images the histogram's shadow count agrees with what the
    clipping overlay actually paints, and each channel's total count equals
    its true pixel count instead of silently under-counting the way the old
    np.histogram path did (it dropped NaN entirely). This agreement is NOT
    guaranteed for linear images (every freshly-loaded FITS, and every
    pre-Stretch pipeline step): to_qimage instead renders those through
    autostretch(), whose median/MAD statistics are not NaN-safe, so a single
    NaN pixel can poison an entire displayed channel to black while this
    function still counts only that one raw pixel in bin 0."""
    finite = np.where(np.isfinite(channel), channel, 0.0)
    q = (finite * 255 + 0.5).astype(np.uint8)
    return np.bincount(q.ravel(), minlength=256)


def histogram(img: AstroImage, bins: int = 256) -> dict:
    """Per-channel pixel counts over [0, 1]. Color -> {'r','g','b'}, mono -> {'l'}."""
    data = np.clip(img.data, 0.0, 1.0)

    def counts(channel: np.ndarray) -> np.ndarray:
        if bins == 256:
            return _counts_256(channel)
        out, _ = np.histogram(channel, bins=bins, range=(0.0, 1.0))
        return out

    if data.ndim == 2:
        return {"l": counts(data)}
    return {key: counts(data[..., i]) for i, key in enumerate(("r", "g", "b"))}
