from __future__ import annotations

from typing import NamedTuple

import numpy as np


class Sample(NamedTuple):
    """One pixel's values. `channels` is (r, g, b) for colour, (v,) for mono;
    `luminance` is the equal-weight channel mean, or None for mono (where the
    single value already is the luminance)."""

    channels: tuple[float, ...]
    luminance: float | None


def sample(data: np.ndarray, x: int, y: int) -> Sample | None:
    """The pixel at (x, y), or None if that lies outside `data`. Single pixel by
    design — averaging a patch would under-report saturated star cores and so
    contradict the clipping overlay drawn beside it."""
    h, w = data.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return None
    if data.ndim == 2:
        return Sample((float(data[y, x]),), None)
    px = data[y, x]
    channels = (float(px[0]), float(px[1]), float(px[2]))
    return Sample(channels, float(sum(channels) / 3.0))


class Clipping(NamedTuple):
    """Worst-channel clipped fractions (0-1) and the channel labels they came
    from. Highlights and shadows are tracked independently: a background crushed
    only in red while a star core blows only in blue is two separate faults."""

    hi_frac: float
    hi_channel: str
    lo_frac: float
    lo_channel: str


_NO_CLIPPING = Clipping(0.0, "", 0.0, "")


def clipping_from_histogram(hist) -> Clipping:
    """Clipped fractions read straight off the 256-bin histogram the canvas
    already computes — the top and bottom bins ARE the clipped pixels, so this
    costs nothing. Reports the worst channel (highest fraction) rather than
    merging them. Each channel's fraction is computed against its own histogram
    sum, not a borrowed denominator, because NaN values in one channel don't
    affect others."""
    if not hist:
        return _NO_CLIPPING

    # Compute per-channel fractions: (fraction, channel, count, sum)
    hi_fractions = []
    lo_fractions = []

    for k, v in hist.items():
        channel_sum = int(v.sum())
        if channel_sum <= 0:
            # A channel with sum 0 (all NaN) contributes 0.0 fraction
            hi_fractions.append((0.0, k.upper(), 0, 0))
            lo_fractions.append((0.0, k.upper(), 0, 0))
        else:
            hi_count = int(v[-1])
            lo_count = int(v[0])
            hi_fractions.append((hi_count / channel_sum, k.upper(), hi_count, channel_sum))
            lo_fractions.append((lo_count / channel_sum, k.upper(), lo_count, channel_sum))

    # Select worst channels by highest fraction (not raw count)
    hi_frac, hi_channel, _, _ = max(hi_fractions, key=lambda x: x[0])
    lo_frac, lo_channel, _, _ = max(lo_fractions, key=lambda x: x[0])

    # Zero-valued clipping types get empty channel names
    if hi_frac == 0.0:
        hi_channel = ""
    if lo_frac == 0.0:
        lo_channel = ""

    return Clipping(hi_frac, hi_channel, lo_frac, lo_channel)


def clip_masks(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(shadow, highlight) boolean masks over a uint8 H×W×3 display array — any
    channel pinned to 0 or 255. The OR form is deliberate: it measures 7 ms on an
    8.3 MP frame against 78 ms for `.any(axis=2)`, which matters because this runs
    inside the live-preview path."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    shadow = (r == 0) | (g == 0) | (b == 0)
    highlight = (r == 255) | (g == 255) | (b == 255)
    return shadow, highlight


class BackgroundModel(NamedTuple):
    image: "AstroImage"      # the removed gradient, normalised for viewing
    span: float              # its strength in the image's own units
    removed_anything: bool


def background_model(before: "AstroImage", after: "AstroImage") -> BackgroundModel:
    """What background extraction took out, as a picture you can look at.

    The model is simply `before - after`, so it is exact by construction rather
    than a second guess at what the tool did — and it needs nothing stored,
    because both images are already in the project's history.

    Seeing it is the point. A background model that is a smooth ramp is the tool
    working; one that carries the SHAPE OF YOUR OBJECT means the fit mistook
    faint outer signal for sky and subtracted the thing you came for. That is
    invisible in the corrected image, where the object merely looks a little
    flat, and obvious here.

    Normalised to 0..1 for display only, because a gradient is a few percent of
    the range and would otherwise be a uniform dark rectangle. `span` reports the
    real strength in the image's own units, so the number is not lost in the
    stretch.

    A difference of nothing stays a difference of nothing: normalising float
    rounding error would paint a vivid pattern out of noise and read as a fault
    in the data. Below the threshold the image is returned flat and
    `removed_anything` is False.
    """
    import numpy as np

    from .image import AstroImage

    diff = np.asarray(before.data, np.float32) - np.asarray(after.data, np.float32)
    lo, hi = float(diff.min()), float(diff.max())
    span = hi - lo
    # 1/1000 of the range is far below anything a stretch could show, and well
    # above float32 error on values of order 0.01
    if span < 1e-3:
        return BackgroundModel(
            AstroImage(np.zeros_like(diff), is_linear=False,
                       metadata=dict(before.metadata)), span, False)
    norm = (diff - lo) / span
    return BackgroundModel(
        AstroImage(norm.astype(np.float32), is_linear=False,
                   metadata=dict(before.metadata)), span, True)
