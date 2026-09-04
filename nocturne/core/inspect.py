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

    # When EVERY channel is clipped by the same fraction, naming one of them is
    # a lie the caller then prints in full ("100% of red crushed to zero" when
    # red, green and blue all died). "ALL" lets it say so instead. Only an exact
    # tie across every channel counts: a near-tie is still worst-channel news.
    if len(hi_fractions) > 1 and all(f == hi_frac for f, *_ in hi_fractions):
        hi_channel = "ALL"
    if len(lo_fractions) > 1 and all(f == lo_frac for f, *_ in lo_fractions):
        lo_channel = "ALL"

    # Zero-valued clipping types get empty channel names
    if hi_frac == 0.0:
        hi_channel = ""
    if lo_frac == 0.0:
        lo_channel = ""

    return Clipping(hi_frac, hi_channel, lo_frac, lo_channel)


# A clipped pixel that survives a mean this wide is a dark REGION; one that does
# not is a single noise excursion below the black point. 3 is the smallest
# window that distinguishes them, and matches what Noise Reduction does to those
# pixels anyway.
_STRUCTURE_BLOCK = 3

# Enough blocks that a fraction is stable, few enough that this stays off the
# live-preview budget. 250k blocks is ~2.25 M sampled pixels of any size frame.
_STRUCTURE_BLOCKS = 250_000


def structural_clipping(rgb: np.ndarray,
                        block: int = _STRUCTURE_BLOCK,
                        target_blocks: int = _STRUCTURE_BLOCKS) -> Clipping:
    """Clipping that is a dark REGION, not a single pixel of noise.

    The histogram measure counts bin 0, which on real data is dominated by
    isolated pixels whose noise dipped below the black point. Measured on
    Andreas' M 31 mosaic after Stretch + Auto Levels: 13.43% of blue at zero,
    spread over 400,964 separate regions of median size ONE pixel, 75.6% of them
    1-2 px — and a plain 3x3 mean leaves 0.020%. He spotted it himself, from the
    report dropping to nothing after Noise Reduction.

    So the raw figure is honest about the pixels and misleading about the harm,
    and it is what made the warning cry wolf: it fires on every stretched image,
    naming a channel, for damage that a later step undoes.

    This is the number to ALARM on. The raw fraction stays the number reported,
    because the "Show clipping" overlay marks exactly those pixels
    (`clip_masks` tests `rgb == 0`) and a headline that disagreed with the
    overlay would be a WYSIWYG break.

    Blocks are strided rather than exhaustive: reshaping a contiguous array and
    slicing the block grid is a VIEW, so only the sampled blocks are ever
    materialised, and this runs on the live-preview path.
    """
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
        return _NO_CLIPPING
    h, w = rgb.shape[:2]
    nby, nbx = h // block, w // block
    if nby < 1 or nbx < 1:
        return _NO_CLIPPING
    grid = rgb[:nby * block, :nbx * block].reshape(nby, block, nbx, block, -1)
    step = max(1, int((nby * nbx / max(1, target_blocks)) ** 0.5))
    sub = grid[::step, :, ::step]
    # `.all` over the two within-block axes: every pixel of the block is dead.
    dead = (sub == 0).all(axis=(1, 3))
    blown = (sub == 255).all(axis=(1, 3))
    names = ("R", "G", "B")

    def worst(flags) -> tuple[float, str]:
        """Worst channel, or "ALL" on an exact tie — the same convention
        `clipping_from_histogram` uses, so the two can never phrase the same
        picture differently. A region dead in every channel really is black,
        and naming one of them would be a lie the caller prints in full."""
        fracs = [float(flags[..., c].mean()) for c in range(3)]
        top = max(fracs)
        if top == 0.0:
            return 0.0, ""
        if all(f == top for f in fracs):
            return top, "ALL"
        return top, names[fracs.index(top)]

    hi_frac, hi_ch = worst(blown)
    lo_frac, lo_ch = worst(dead)
    return Clipping(hi_frac, hi_ch, lo_frac, lo_ch)


def clip_masks(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(shadow, highlight) boolean masks over a uint8 H×W×3 display array, PER
    CHANNEL — same H×W×3 shape as the input, so `shadow[..., 0]` is "red is at
    zero here".

    Per channel rather than OR-ed flat, because which channel died is the whole
    story and the flat form hid it. A background where only red is at zero still
    looks a perfectly healthy teal, so a user checks whether the pixel is
    #000000, finds it is not, and concludes the warning is wrong — it is not,
    the Ha in that region is simply gone. The caller colours the overlay by
    channel so the picture says which.

    Two vectorised comparisons over the whole array; the caller combines them
    with bitwise ops rather than `.any(axis=2)`, which measures 78 ms on an
    8.3 MP frame against 7 ms, and this runs in the live-preview path."""
    return rgb == 0, rgb == 255


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

    Brightened for display only, because a gradient is a fraction of a percent of
    the range and would otherwise be a uniform dark rectangle. `span` reports the
    real strength in the image's own units, so the number is not lost.

    **Mid-grey means nothing was removed there.** Each channel is centred on its
    own median first, because extraction takes out a per-channel PEDESTAL as well
    as a ramp, and a pedestal is a level, not a gradient. Sharing one lo/hi across
    the channels turned that offset into colour: on NGC7000_163x20s_54min the
    per-channel medians were R -0.000428, G +0.000179, B +0.000222 against a span
    of 0.00106, so red landed 0.57 below the others and the model rendered vivid
    cyan — while the actual ramp was STRONGEST IN RED (0.000419 / 0.000274 /
    0.000376). The picture said the opposite of the measurement.

    Amplitude is then scaled by a single shared half-range, not per channel, so a
    genuinely stronger gradient in one channel still reads as colour. Sky-glow is
    not grey and the view should not pretend it is.

    A difference of nothing stays a difference of nothing: normalising float
    rounding error would paint a vivid pattern out of noise and read as a fault in
    the data. Below the threshold the image is returned flat and
    `removed_anything` is False.
    """
    import numpy as np

    from .image import AstroImage

    diff = np.asarray(before.data, np.float32) - np.asarray(after.data, np.float32)
    span = float(diff.max() - diff.min())
    # float32 error on values of order 0.01 is ~1e-7, so 1e-6 is comfortably
    # above noise. The previous 1e-3 floor was six percent BELOW a real
    # measurement — NGC 7000's gradient spanned 0.00106 for a 5.2% correction —
    # so a slightly flatter sky would have been called nothing.
    if span < 1e-6:
        return BackgroundModel(
            AstroImage(np.zeros_like(diff), is_linear=False,
                       metadata=dict(before.metadata)), span, False)
    centred = diff - np.median(diff.reshape(-1, diff.shape[-1]), axis=0) \
        if diff.ndim == 3 else diff - np.median(diff)
    half = float(np.abs(centred).max()) or 1.0
    norm = np.clip(centred / (2.0 * half) + 0.5, 0.0, 1.0)
    return BackgroundModel(
        AstroImage(norm.astype(np.float32), is_linear=False,
                   metadata=dict(before.metadata)), span, True)
