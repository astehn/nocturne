from __future__ import annotations

import numpy as np

from .image import AstroImage

_TARGET_BG = 0.25  # target median for the stretched display
_SIGMA = 2.8


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
    med = float(np.nanmedian(c))
    mad = float(np.nanmedian(np.abs(c - med))) or 1e-6
    shadow = max(0.0, med - _SIGMA * mad)
    clipped = np.clip((c - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
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


def neutral_stretch(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """Neutralise the background, then stretch every channel with ONE curve.

    The stretch's job is brightness, not colour, and the per-channel (unlinked)
    version had an opinion it should not have had. It gives each channel a gain
    of roughly target/(sigma*MAD), and a Bayer sensor gives green half the noise
    of red and blue because it has twice as many green photosites — so green was
    amplified about 1.9x harder than the other channels. On a real M 31 mosaic
    that turned a 3.6% green DEFICIT in the data into a 4.7% green EXCESS on
    screen, and in the exported file. Remove Green could not fix it: it runs
    before the stretch, and the stretch re-normalised each channel afterwards.

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
        meds.append(float(np.nanmedian(ch)) if np.isfinite(ch).any() else 0.0)
    ref = float(np.mean(meds))
    out = np.stack([d[:, :, c] - (meds[c] - ref) for c in range(d.shape[2])], axis=2)

    if not np.isfinite(out).any():
        return np.clip(np.nan_to_num(out), 0.0, 1.0)
    mad = float(np.nanmedian(np.abs(out - ref))) or 1e-6
    shadow = max(0.0, ref - _SIGMA * mad)
    clipped = np.clip((out - shadow) / max(1e-6, 1.0 - shadow), 0.0, 1.0)
    m = _mtf_midtones(float(np.nanmedian(clipped)) or 1e-6, target)
    return _apply_params(out, shadow, m)


def autostretch(img: AstroImage) -> np.ndarray:
    # Display-only: lift the background to a fixed target for a clear preview.
    # Neutralise-then-link, so the sky is neutral and no channel is crushed
    # WITHOUT the stretch inventing a colour cast of its own — see
    # neutral_stretch. Matches the committed stretch, so the preview equals the
    # exported result at every step.
    return neutral_stretch(img.data, _TARGET_BG)
