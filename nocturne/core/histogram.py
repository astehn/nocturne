from __future__ import annotations

import numpy as np

from .autostretch import _sample
from .image import AstroImage, finite_or_zero


def _counts_256(channel: np.ndarray) -> np.ndarray:
    """256 bins straight off the uint8 quantisation the canvas already uses, so
    bin 255 means exactly 'displays as pure white' — the same test the clipping
    overlay applies. ~4x faster than np.histogram over float32.

    Non-finite values are replaced with 0.0 before the cast (see
    image.finite_or_zero for why that is the app-wide convention): the naive
    `(nan * 255 + 0.5).astype(np.uint8)` also produces 0, but raises a
    RuntimeWarning on every canvas update. Landing NaN in bin 0 means each
    channel's total equals its true pixel count instead of silently
    under-counting the way the old np.histogram path did — it dropped NaN
    entirely.

    A NaN pixel counted here in bin 0 is also painted black by the canvas, for
    linear and non-linear images alike. That used to hold only post-Stretch:
    linear images render through autostretch(), whose median/MAD were not
    NaN-safe, so one NaN pixel blanked a whole displayed channel while this
    function counted just the one. Both halves are fixed — import zeroes
    non-finite data and _stretch_params ignores it — so the two agree about NaN
    at every step. (They still differ about everything else pre-Stretch, by
    design: the canvas autostretches for display and this does not.)"""
    q = (finite_or_zero(channel) * 255 + 0.5).astype(np.uint8)
    return np.bincount(q.ravel(), minlength=256)


def histogram(img: AstroImage, bins: int = 256) -> dict:
    """Per-channel pixel counts over [0, 1]. Color -> {'r','g','b'}, mono -> {'l'}.

    Large images are SAMPLED. This cost 0.29 s of every live-preview tick on a
    39.5 Mpx master, to draw a widget a few hundred pixels wide — and a
    histogram is a shape, which a few hundred thousand pixels describe as well
    as forty million. The counts are therefore a sample, not a census; the
    clipping readout is unaffected because it reports FRACTIONS, and a strided
    sample preserves those.

    Below the threshold nothing is skipped, so small images keep an exact
    census. The stride comes from the shape alone (see autostretch._sample), so
    the same image always gives the same histogram.
    """
    data = _sample(np.clip(img.data, 0.0, 1.0))

    def counts(channel: np.ndarray) -> np.ndarray:
        if bins == 256:
            return _counts_256(channel)
        out, _ = np.histogram(channel, bins=bins, range=(0.0, 1.0))
        return out

    if data.ndim == 2:
        return {"l": counts(data)}
    return {key: counts(data[..., i]) for i, key in enumerate(("r", "g", "b"))}
