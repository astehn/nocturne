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


class ClipBaseline(NamedTuple):
    """A `clip_masks()` snapshot at some reference settings (e.g. black=0,
    white=1 — the tool doing nothing), so a later `clip_masks(rgb, baseline=...)`
    call can report only what changed since.

    Same split as `main_window._clip_baseline`, one level lower: that one
    diffs two SCALAR fractions from the histogram to keep the live-preview
    ALARM from crying wolf on damage the session didn't cause. This one diffs
    the actual per-pixel MASKS, because the overlay has to light specific
    pixels, not just adjust a percentage — a starless layer that already has
    2-6% of its shadows at zero (auto_levels's black point crushes part of the
    noise floor by construction, measured 2026-09-09) must not relight those
    same pixels the moment Starless Levels opens with black=0.

    Fractions are stored alongside the masks — per-pixel (`.any(axis=2)`), the
    same rule `paint_clipping` uses to decide a pixel is marked at all — so a
    caller can state "N% already crushed on arrival" without recomputing
    anything.
    """
    shadow: np.ndarray        # H x W x 3 bool, from clip_masks
    highlight: np.ndarray     # H x W x 3 bool, from clip_masks
    shadow_frac: float
    highlight_frac: float


def capture_clip_baseline(rgb: np.ndarray) -> ClipBaseline:
    """Snapshot `clip_masks(rgb)` as a `ClipBaseline` for later diffing.

    A separate call, not a flag on `clip_masks`, because a baseline is
    captured ONCE — a dialog opening, or a session's arrival state — while
    `clip_masks` itself runs on every live-preview tick; folding fraction
    bookkeeping into the hot path would cost every caller for a number only
    one of them wants.
    """
    shadow, highlight = clip_masks(rgb)
    return ClipBaseline(shadow, highlight,
                        float(shadow.any(axis=2).mean()),
                        float(highlight.any(axis=2).mean()))


def clip_masks(rgb: np.ndarray,
               baseline: ClipBaseline | None = None) -> tuple[np.ndarray, np.ndarray]:
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
    8.3 MP frame against 7 ms, and this runs in the live-preview path.

    `baseline`, when given, is subtracted out: a pixel clipped there too is NOT
    reported here, so a caller sees only what changed since the baseline was
    captured, per the ruling in round2-task-B — "light only what was added,
    still report the total" (the total lives in `baseline.shadow_frac` /
    `.highlight_frac`, not here). Defaults to None so every existing caller —
    `paint_clipping` on the main window's live-preview tick chief among them —
    is byte-for-byte unaffected; the extra branch and two bitwise ops only run
    for a caller that opts in."""
    sh, hi = rgb == 0, rgb == 255
    if baseline is not None:
        if baseline.shadow.shape != sh.shape:
            raise ValueError(
                "clip baseline shape does not match rgb: "
                f"{baseline.shadow.shape} vs {sh.shape}")
        sh = sh & ~baseline.shadow
        hi = hi & ~baseline.highlight
    return sh, hi


# --- the ONE clipping legend, shared by the canvas and the dialogs ----------
#
# The shadow mark is built ADDITIVELY from the channels that died: red, green
# or blue for one; yellow, magenta or cyan for two; white for all three. So the
# colour of the mark IS the answer to "which channel is gone", and white —
# every channel lit — is the only case where the pixel really is black. That
# matters: an earlier draft of this painted white for two dead channels too,
# which says "black" about a pixel that is still, say, dark blue. Andreas
# checked a flagged region against Photoshop, found healthy colour, and
# reasonably read the old flat blue as a false alarm. It was not: only red had
# died, and in an HOO palette red is Ha.
CLIP_MARK_ON = 255       # a channel that is clipped
CLIP_MARK_OFF = 60       # one that is not — dark enough to read as absent
# Highlights stay a single colour. On this sensor they are vanishingly rare —
# 0.00002% measured on real captures, because Seestar star cores do not
# saturate — and a second three-hue palette would cost readability for the case
# that actually happens. Amber sits outside the shadow palette, so the two can
# never be read as each other.
CLIP_HIGHLIGHT = (255, 160, 0)


def paint_clipping(rgb: np.ndarray, out: np.ndarray | None = None,
                   baseline: ClipBaseline | None = None) -> np.ndarray:
    """Paint the clipping legend for `rgb` into `out` (default: `rgb` itself).

    `baseline`, forwarded to `clip_masks`, restricts the paint to pixels newly
    clipped since it was captured — see `ClipBaseline`. None (the default)
    paints the total, exactly as before; this is what the main window's
    live-preview tick uses, unchanged.

    ONE implementation, because the legend is a thing the user LEARNS. The main
    window's Show Clipping tooltip teaches channel colour = crushed, amber =
    blown; a second painting with its own scheme meant white said "all three
    crushed" on the canvas and "all three blown" in a dialog, so a user who
    pulled the white point in and saw white specks read them as exactly the
    opposite of what they were.

    `out` separate from `rgb` is what lets the same painting serve both callers:
    the canvas paints over the picture, so unclipped pixels keep their colour,
    while `clip_overlay` paints onto a black field and the picture is replaced.

    Nested np.where per channel, NOT `out[any_sh] = marks[any_sh]`. Measured on
    an 8.3 MP frame with 6.6% clipped: this form 38.5 ms against 63.4 for the
    fancy-index form and 40.2 for masked assignment, where the flat-blue paint
    it replaces cost 33.3. Five milliseconds for naming the channel is the whole
    price, and this runs on every live-preview tick.

    The marks are passed as np.uint8 SCALARS, not the plain ints they read as
    above: `np.where(mask, 255, 60)` promotes to int64, so each channel built an
    8-byte intermediate — 66 MB per channel on that frame — and threw seven
    eighths of it away in the cast back to uint8. Same form, same result, 27.9 ms
    to 20.0.
    """
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError("paint_clipping needs an H x W x 3 uint8 array; "
                         f"got shape {rgb.shape}")
    if out is None:
        out = rgb
    on, off = np.uint8(CLIP_MARK_ON), np.uint8(CLIP_MARK_OFF)
    sh, hi = clip_masks(rgb, baseline=baseline)
    r0, g0, b0 = sh[..., 0], sh[..., 1], sh[..., 2]
    any_sh = r0 | g0 | b0
    for i, dead in enumerate((r0, g0, b0)):
        out[..., i] = np.where(any_sh, np.where(dead, on, off), out[..., i])
    # Highlights painted last: a pixel can be 0 in one channel and 255 in
    # another, and a blown core is the more urgent of the two. Bitwise, not
    # .any(axis=2) — 7 ms against 78 on an 8.3 MP frame.
    out[hi[..., 0] | hi[..., 1] | hi[..., 2]] = CLIP_HIGHLIGHT
    return out


def clip_overlay(rgb: np.ndarray, shape: tuple[int, int],
                 baseline: ClipBaseline | None = None) -> np.ndarray:
    """`paint_clipping` onto a black field, reduced to `shape` with a MAXIMUM
    rather than an average.

    `baseline`, forwarded to `paint_clipping`, must be captured at the SAME
    shape as `rgb` (not `shape` — that is only the display target). A caller
    diffing against a zoomed crop or a resized composite needs to capture a
    matching-shape baseline itself; `clip_masks` raises rather than silently
    misaligning if the shapes disagree.

    The reduction is the point. The preview runs on a decimated copy for speed,
    and averaging a 4x4 block containing one blown pixel yields 255/16 = 16 —
    invisible. A user drags the white point until the first specks appear, so an
    overlay that dilutes isolated pixels hides exactly the signal it exists to
    show. Any clipped pixel inside a block lights the whole block: over-reporting
    at preview scale is a wrong colour on one block, under-reporting is a blown
    core the user never sees.

    `shape` should be the size the overlay will be DISPLAYED at, not an
    arbitrary intermediate: a smooth rescale afterwards re-dilutes exactly what
    the block-max preserved (measured: an isolated lit block drops to 195 / 111
    / 55 depending on the factor), which can leave a blown speck dimmer than a
    flat crushed background and invert the legend again.
    """
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        # Its neighbour structural_clipping guards the same way. Without this a
        # 2D array passes the identity branch and dies inside np.pad with a
        # broadcast error that names neither the caller nor the cause.
        raise ValueError("clip_overlay needs an H x W x 3 uint8 array; "
                         f"got shape {rgb.shape}")
    out = paint_clipping(rgb, np.zeros_like(rgb), baseline=baseline)
    h, w = shape
    src_h, src_w = out.shape[:2]
    if (src_h, src_w) == (h, w):
        return out
    # Pad to a whole number of blocks so the trailing edge is not silently
    # dropped — but only when there IS a trailing edge: np.pad always copies,
    # which is 24 MB on an 8.3 MP frame.
    bh, bw = -(-src_h // h), -(-src_w // w)
    if bh * h != src_h or bw * w != src_w:
        out = np.pad(out, ((0, bh * h - src_h), (0, bw * w - src_w), (0, 0)),
                     mode="constant")
    # Rows then columns, accumulating with np.maximum, NOT one
    # `reshape(h, bh, w, bw, 3).max(axis=(1, 3))`. Identical result; the
    # five-dimensional form reduces over two interleaved non-adjacent axes and
    # measures 97.1 ms on an 8.3 MP frame against 4.4 for this, which is 60% of
    # the whole preview tick for an operation that only touches 25 MB once.
    # (Two chained single-axis `.max()` calls are 13.6 ms — better, still 3x
    # this.) Each pass is a handful of full-width elementwise maxima, which is
    # the access pattern the memory system is built for.
    rows = out.reshape(h, bh, out.shape[1], 3)
    acc = rows[:, 0].copy()
    for k in range(1, bh):
        np.maximum(acc, rows[:, k], out=acc)
    cols = acc.reshape(h, w, bw, 3)
    acc = cols[:, :, 0].copy()
    for k in range(1, bw):
        np.maximum(acc, cols[:, :, k], out=acc)
    return acc


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
