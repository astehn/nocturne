from __future__ import annotations

import numpy as np

from .image import AstroImage

# THE one fact: the sky brightness a default stretch aims for. The linear
# display preview uses it, and the Stretch step's slider default is DERIVED from
# it (steps/stretch_step._DEFAULT), so the picture cannot change when you arrive
# at Stretch without touching anything.
#
# It was two hand-maintained numbers until 2026-09-15 — 0.25 here and a 0.30
# slider default targeting 0.205 — and they drifted apart the moment the default
# moved on 2026-09-14. Walking into Stretch darkened the canvas 18%, about 10
# levels of 255, before the user did a thing. Andreas noticed independently.
#
# 0.205 rather than 0.25 because that is what the committed default produces,
# and because the whole AstroWizard investigation established Nocturne was
# showing the sky too bright; this was the last surface still doing it. Checked
# on IC 1396A, NGC 6888 and M 31 that the darker view still shows the faint
# structure you need to judge an unstretched frame by.
DEFAULT_TARGET_BG = 0.205
_TARGET_BG = DEFAULT_TARGET_BG  # target median for the stretched display
_SIGMA = 2.8


_SAMPLE_TARGET = 200_000    # samples per channel for deriving statistics


def _sample(a: np.ndarray) -> np.ndarray:
    """A strided view for deriving statistics, or the array itself if small.

    The stretch needs four scalars — two medians and two MADs — and taking them
    over every pixel was 61% of its cost on a 39.5 Mpx master: 1.4 s of 2.3 s.
    A sample of ~200k pixels returns the same scalars to within 4.4e-7, measured
    on that master, which is four orders of magnitude below one step of an 8-bit
    display.

    The stride comes from the SHAPE and nothing else, so the same image always
    yields the same parameters. A random sample would make two exports of one
    image differ. The 200k target and this trick are the stacker's, from
    normalize.py, where the same reasoning applies to per-frame sky levels.
    """
    n = a.shape[0] * a.shape[1]
    if n <= _SAMPLE_TARGET:
        return a
    step = int(np.sqrt(n / _SAMPLE_TARGET)) + 1
    return a[::step, ::step]


def _mtf(m: float, x: np.ndarray) -> np.ndarray:
    # Midtones transfer function (PixInsight/Siril style). np.where evaluates
    # both branches, so a near-zero denominator can warn even though the result
    # is masked/clipped downstream — silence that spurious warning.
    num = (m - 1.0) * x
    den = (2.0 * m - 1.0) * x - m
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = num / den
    return np.where(x == 0, 0.0, np.where(x == 1, 1.0, ratio))


def _stretch_params(c: np.ndarray, target: float = _TARGET_BG) -> tuple[float, float]:
    """Derive (shadow clip, midtones m) from one channel's statistics so its
    median maps to `target`.

    NaN-aware because these are two scalars derived from the WHOLE channel: with
    plain np.median a single NaN sample made both of them NaN, and every pixel
    then stretched to NaN — one bad pixel blanked 400 of 400, verified. Import
    now zeroes non-finite data (fits_io._normalize), but NaN can still arise
    mid-pipeline from a division or an external tool's output, and a statistic
    that collapses on one bad sample is a bad statistic regardless of who feeds
    it.

    NaN specifically, not Inf: a median is robust to Inf (it is just the largest
    sample, so it shifts the result by one rank), and np.nanmedian ignores NaN
    only. An Inf that reached here would survive _apply_params' clip as 1.0 and
    display white rather than the black the no-data convention gives NaN — an
    inconsistency left alone deliberately, since import zeroes Inf and no
    in-pipeline source of it is known. Revisit if one turns up.
    """
    if not np.isfinite(c).any():
        return 0.0, 0.5          # no statistics to derive from; leave it alone
    s = _sample(c)
    med = float(np.nanmedian(s))
    mad = float(np.nanmedian(np.abs(s - med))) or 1e-6
    shadow = max(0.0, med - _SIGMA * mad)
    # the second median is derived from the sample too — clipping the whole
    # channel here would put the expensive pass straight back
    clipped = np.clip((s - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    med2 = float(np.nanmedian(clipped)) or 1e-6
    return shadow, _mtf_midtones(med2, target)


def linked_stretch(data: np.ndarray, target: float) -> np.ndarray:
    """Adaptive midtones stretch. For color, one transfer is derived from
    luminance and applied to every channel (preserves colour balance)."""
    if data.ndim == 2:
        shadow, m = _stretch_params(data, target)
        return np.clip(_apply_params(data, shadow, m), 0.0, 1.0)
    lum = data.mean(axis=2)
    shadow, m = _stretch_params(lum, target)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        out[..., ch] = _apply_params(data[..., ch], shadow, m)
    return np.clip(out, 0.0, 1.0)


def unlinked_stretch(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """Per-channel display stretch: each channel independently stretched so its
    own median hits `target`. Neutralizes a uniform sky-colour cast (twilight,
    moon, light pollution) — the Siril-style preview stretch. Display-only;
    the editor keeps the colour-faithful linked_stretch."""
    if data.ndim == 2:
        return linked_stretch(data, target)
    out = np.empty_like(data, dtype=np.float32)
    for ch in range(data.shape[2]):
        shadow, m = _stretch_params(data[..., ch], target)
        out[..., ch] = _apply_params(data[..., ch], shadow, m)
    return np.clip(out, 0.0, 1.0)


def _apply_params(c: np.ndarray, shadow: float, m: float) -> np.ndarray:
    clipped = np.clip((c - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    return _mtf(m, clipped).astype(np.float32)


def _mtf_midtones(current_med: float, target: float) -> float:
    # Solve MTF midtones param so that _mtf(m, current_med) == target.
    if current_med <= 0:
        return 0.5
    return ((target - 1.0) * current_med) / (
        (2.0 * target - 1.0) * current_med - target
    )


# --- stretch versions ---------------------------------------------------------
# A stored Stretch option carries the version it was made with ("version" in
# its dict; absent means 1), because Stretch is REPLAYED when a project or a
# recipe is reopened: change the maths under an old option and every saved
# picture silently changes. Each version is kept as its own function.
#
#   1  whole-frame medians, one black point from the MAD pooled over the three
#      channels (until 2026-10-11)
#   2  sky medians, black point from the noisiest channel (from 2026-10-11)
STRETCH_V1 = 1
STRETCH_V2 = 2
# THE REVERT SWITCH: the version every NEW stretch uses — the Stretch step, its
# live preview, the visual picker, the linear display, Auto Enhance and new
# recipes. Set it back to STRETCH_V1 to return to the old stretch. Stretches
# already saved keep the version they recorded, either way.
STRETCH_VERSION = STRETCH_V2

# Version 2's sky. The darkest 30% of a smoothed luminance: the prototype's
# choice, and on M 45 and IC 1396A it separated sky from nebula in his renders
# (2026-10-11). The smoothing keeps the mask from picking pixels that are dark
# only because of noise, which would bias each channel by its own noise. It is
# a fraction of the short edge, not pixels, so the 640 px picker and the full
# frame pick the same sky: the prototype's 31 px on M 45's 4320 px short edge.
_SKY_PCT = 30.0
_SKY_SMOOTH = 31 / 4320
# The luminance is reduced to about this many cells on the long edge before
# smoothing: a few ms instead of a full-resolution filter, and the block mean
# is itself part of the smoothing.
_SKY_EDGE = 512
# Below this in EVERY channel a pixel is not data (untrimmed stack edge,
# rotation corner, mosaic gap); the same threshold as narrowband._GB_DATA_EPS.
# His linear states never go below 0.0048 (study 2026-10-11), so no sky pixel
# is anywhere near it.
_DATA_EPS = 1e-4
# Fewer sky samples than this and the sky medians are noise; use every data
# pixel instead (the version 1 statistic, minus the border).
_SKY_MIN_SAMPLES = 64


def neutral_stretch(data: np.ndarray, target: float = _TARGET_BG,
                    version: int | None = None) -> np.ndarray:
    """The linked stretch, in the given version (`None`: STRETCH_VERSION)."""
    v = STRETCH_VERSION if version is None else int(version)
    if v == STRETCH_V1:
        return _neutral_stretch_v1(data, target)
    if v == STRETCH_V2:
        return _neutral_stretch_v2(data, target)
    raise ValueError(f"unknown stretch version {version!r}")


def _smoothed_luminance(d: np.ndarray, data: np.ndarray):
    """(smoothed luminance, data pixels per window, block size, usable cells)
    on a block-mean grid. Averaged over data pixels only, by normalised
    convolution, so a black border neither reads as sky nor darkens the sky
    beside it."""
    from scipy.ndimage import uniform_filter
    from skimage.transform import downscale_local_mean
    h, w = d.shape[:2]
    b = max(1, max(h, w) // _SKY_EDGE)
    lum = d[..., 0].astype(np.float32, copy=True)
    for c in range(1, d.shape[2]):
        lum += d[..., c]
    lum = np.where(data, lum / d.shape[2], 0.0).astype(np.float32)
    wt = data.astype(np.float32)
    if b > 1:
        lum = downscale_local_mean(lum, (b, b)).astype(np.float32)
        wt = downscale_local_mean(wt, (b, b)).astype(np.float32)
    size = max(3, int(round(_SKY_SMOOTH * min(lum.shape))))
    num = uniform_filter(lum, size, mode="nearest")
    den = uniform_filter(wt, size, mode="nearest")
    smooth = num / np.maximum(den, 1e-6)
    return smooth, den * float(size * size * b * b), b, wt > 0.5


def _sky_samples(s: np.ndarray, s_data: np.ndarray, d: np.ndarray,
                 data: np.ndarray, step: int) -> np.ndarray:
    """Which of the sampled pixels are sky: the darkest _SKY_PCT of the
    smoothed luminance, over data pixels.

    Each pixel's OWN value is taken out of the smoothed luminance it is judged
    by. Otherwise a pixel that is dark only because of its noise votes itself
    into the sky, and every channel's sky median comes out low in proportion to
    that channel's noise — blue more than green, the very bias this version
    removes. On a full frame the pixel is 1 of ~900 in its window and this is
    nothing; on a small image it was 1 of 9 and put the sky 2 levels apart."""
    h, w = d.shape[:2]
    smooth, count, b, good = _smoothed_luminance(d, data)
    rows = np.minimum(np.arange(0, h, step) // b, smooth.shape[0] - 1)
    cols = np.minimum(np.arange(0, w, step) // b, smooth.shape[1] - 1)
    cell = np.ix_(rows, cols)
    own = s.mean(axis=2)
    n = count[cell]
    judged = (smooth[cell] * n - own) / np.maximum(n - 1.0, 1.0)
    usable = s_data & good[cell]
    if int(usable.sum()) < _SKY_MIN_SAMPLES:
        return s_data
    cut = float(np.percentile(judged[usable], _SKY_PCT))
    sky = usable & (judged <= cut)
    return sky if int(sky.sum()) >= _SKY_MIN_SAMPLES else s_data


def stretch_v2_params(data: np.ndarray, target: float = _TARGET_BG):
    """(per-channel sky medians, ref, shadow, midtones, data mask) for version 2.

    Split out so a test can compare what the downscaled picker and the full
    frame measure, not just the pictures."""
    d = np.asarray(data, dtype=np.float32)
    # NaN in any channel makes the max NaN, so that pixel is not data either.
    # Channel by channel: a reduction over the last axis of H x W x 3 is 3x slower.
    peak = d[..., 0]
    for c in range(1, d.shape[2]):
        peak = np.maximum(peak, d[..., c])
    with np.errstate(invalid="ignore"):
        data_mask = peak > _DATA_EPS
    h, w = d.shape[:2]
    s = _sample(d)                      # through _sample, so a test can turn it off
    s_data = _sample(data_mask)
    step = (1 if s.shape[:2] == (h, w)
            else int(np.sqrt(h * w / _SAMPLE_TARGET)) + 1)      # _sample's stride
    nch = d.shape[2]
    if not s_data.any():
        return [0.0] * nch, 0.0, 0.0, 0.5, data_mask

    s_sky = _sky_samples(s, s_data, d, data_mask, step)
    meds = [float(np.median(s[..., c][s_sky])) for c in range(nch)]
    ref = float(np.mean(meds))

    vals = s[s_data] - (np.asarray(meds, np.float32) - ref)        # (N, C)
    # FIX2: the black point from the NOISIEST channel. A MAD pooled over the
    # three is mostly green's, which has half the noise on a Bayer sensor, so
    # the noisier channel's low tail went under the shared black point: 10.8% of
    # M 45's blue and 5.6% of IC 1396A's red at zero (study 2026-10-11).
    mad = max(float(np.median(np.abs(vals[:, c] - ref))) for c in range(nch)) or 1e-6
    shadow = max(0.0, ref - _SIGMA * mad)
    clipped = np.clip((vals - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    m = _mtf_midtones(float(np.median(clipped)) or 1e-6, target)
    return meds, ref, shadow, m, data_mask


def _neutral_stretch_v2(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """STRETCH VERSION 2: version 1's neutralise-then-link, measured on the sky.

    Version 1 neutralised each channel on its WHOLE-FRAME median, which a large
    nebula pulls up in its own colour: M 45's blue reflection nebula left the sky
    5 levels low in blue, IC 1396A's Ha left it 13 levels low in red. Version 2
    takes the medians over the sky (see _sky_samples) and the black point from the
    noisiest channel's MAD. On his decon states at the default amount (sky
    median R/G/B in 8-bit levels, the hit channel's share at zero):
        M 45      v1 47/49/44, B 10.84%    v2 49/49/49, B 1.23%
        IC 1396A  v1 34/47/46, R 5.63%     v2 48/48/48, R 0.23%
    (The prototype he judged gave 1.25% and 0.26%.) Andreas compared the two
    full size and chose version 2 (2026-10-11).

    A tight crop with no sky makes the darkest 30% faint nebula, which is then
    neutralised. Version 1 neutralised the MEDIAN nebula there, so version 2's
    shift is the smaller of the two on a nebula that brightens
    in its own colour (tested on a synthetic tight crop).

    Unchanged from version 1, deliberately: the shift is additive, one shadow
    and one midtones value serve all three channels (a gain per channel is what
    invented green, see version 1), and statistics come from a shape-derived
    stride. Black border pixels take no part in any statistic and stay 0.
    A mono frame has no sky colour to neutralise: it stretches as version 1.
    """
    d = np.asarray(data, dtype=np.float32)
    if d.ndim == 2:
        return _neutral_stretch_v1(d, target)
    meds, ref, shadow, m, data_mask = stretch_v2_params(d, target)
    shift = (np.asarray(meds, np.float32) - np.float32(ref)).astype(np.float32)
    with np.errstate(invalid="ignore"):
        out = _apply_params(d - shift, shadow, m)
    if not data_mask.all():
        out[~data_mask] = 0.0
    return out


def _neutral_stretch_v1(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """STRETCH VERSION 1 (until 2026-10-11), kept byte-for-byte so every stretch
    saved before version 2 replays exactly as it was made. Do not edit.

    Neutralise the background, then stretch every channel with ONE curve.

    The stretch's job is brightness, not colour, and the per-channel (unlinked)
    version had an opinion it should not have had. It gives each channel a gain
    of roughly target/(sigma*MAD), and a Bayer sensor gives green half the noise
    of red and blue because it has twice as many green photosites — so green was
    amplified about 1.9x harder than the other channels. On a real M 31 mosaic
    that turned a 3.6% green DEFICIT in the data into a 4.7% green EXCESS on
    screen, and in the exported file.

    (That last argument EXPIRED on 2026-09-13. It used to read "De-green Sky
    could not fix it: it runs before the stretch, and the stretch re-normalised
    each channel afterwards." De-green Sky is now its own stage immediately
    AFTER Stretch, for exactly that reason — so the one objection that made an
    unlinked stretch unofferable no longer holds. See TODO, "should Nocturne
    offer an unlinked stretch".)

    Two jobs were conflated. Setting a black point per channel is right — it is
    what stops the lowest channel clipping on light-polluted OSC data, and why
    the unlinked version was chosen. Setting a GAIN per channel is wrong. So the
    background is levelled additively first, which is what makes the sky neutral
    and keeps every channel off the floor, and then one shadow point and one
    midtones value are applied to all three. An additive offset leaves signal
    ABOVE the background untouched, so the data's own colour survives.

    Measured colour drift from the linear truth, over five real captures across
    two sites and both filters:

        image                   unlinked   linked   this
        M 31 mosaic (IRCUT)      +0.124    -0.011   -0.021
        NGC 7000 (LP)            +0.064    -0.034   -0.039
        M 8 (LP)                 +0.039    +0.015   +0.011
        M 31 device mosaic       +0.069    +0.009   +0.003
        M 45 (Bortle 3/4)        +0.061    +0.002   +0.001

    Plain linked is not the answer either: on M 45 it crushed a whole channel to
    zero, which is precisely the failure the unlinked version existed to avoid.
    """
    d = np.asarray(data, dtype=np.float32)
    if d.ndim == 2:
        shadow, m = _stretch_params(d, target)
        return _apply_params(d, shadow, m)

    meds = []
    for c in range(d.shape[2]):
        ch = d[:, :, c]
        meds.append(float(np.nanmedian(_sample(ch))) if np.isfinite(ch).any() else 0.0)
    ref = float(np.mean(meds))
    out = np.stack([d[:, :, c] - (meds[c] - ref) for c in range(d.shape[2])], axis=2)

    if not np.isfinite(out).any():
        return np.clip(np.nan_to_num(out), 0.0, 1.0)
    mad = float(np.nanmedian(np.abs(_sample(out) - ref))) or 1e-6
    shadow = max(0.0, ref - _SIGMA * mad)
    clipped = np.clip((_sample(out) - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    m = _mtf_midtones(float(np.nanmedian(clipped)) or 1e-6, target)
    return _apply_params(out, shadow, m)


def autostretch(img: AstroImage, *, linked: bool = True) -> np.ndarray:
    # Display-only: lift the background to a fixed target for a clear preview.
    #
    # `linked` is a VIEW preference the caller passes; there is deliberately no
    # module-level default holding it. A stored one would let every measurement
    # that renders through here follow the canvas, and a metric that moves with
    # how you are looking at the image is the failure this project has hit three
    # times. metrics._display therefore keeps the default, on purpose.
    # Neutralise-then-link, so the sky is neutral and no channel is crushed
    # WITHOUT the stretch inventing a colour cast of its own — see
    # neutral_stretch. Matches the committed stretch, so the preview equals the
    # exported result at every step.
    return (neutral_stretch if linked else unlinked_stretch)(img.data, _TARGET_BG)
