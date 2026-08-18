from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage


@dataclass
class ColorSettings:
    neutralize_background: bool = True
    remove_green: bool = False
    method: str = "sky"           # "sky" (background balance) or "photometric" (SPCC)
    # Deliberate colour-cast controls, -1..+1, 0 = untouched. See tint_gains.
    tint: float = 0.0             # -1 green  ..  +1 magenta
    temperature: float = 0.0      # -1 cool   ..  +1 warm


# Luminance weights (Rec. 709), used to hold brightness constant while colour
# moves. Without this the sliders double as an exposure control and a user
# cannot tell which one they are actually operating.
_LUM_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)

# Full-scale gain spread. Calibrated, not guessed: on the M 45 master the
# nebulosity carried a magenta cast of +0.0237 on a (R+B)/2 - G axis, and at
# this value a tint of -0.75 lands it at +0.0014 (neutral) while -1.00 slightly
# overshoots to -0.0053. So the worst measured cast is corrected at about
# three-quarters of travel, leaving headroom for deliberate effect rather than
# making the slider bottom out on a correction.
_TINT_SPREAD = 0.35


def tint_gains(tint: float, temperature: float) -> tuple:
    """Per-channel multiplicative gains for a colour-cast move.

    MULTIPLICATIVE, and applied to LINEAR data at the colour step, for three
    reasons measured on real M 45 data (2026-08-18):

    * An ADDITIVE move here is erased. `neutral_stretch` re-levels the
      background additively afterwards, so a +0.002 green offset produced a
      colour shift of exactly 0.00000. A multiplicative one survives.
    * A gain preserves the RATIOS between channels, so the colour differences
      between stars survive. A clamp (which is what mirroring SCNR would give)
      removes the difference between an orange star and a blue one at the same
      time as it removes the cast.
    * This is also how photographic tools work: Lightroom and Camera Raw apply
      temperature and tint as multipliers on linear raw data before the tone
      curve, not as Lab offsets after it.

    Exposure-neutral by construction: the luminance-weighted mean gain is 1, so
    these two controls change colour and nothing else.
    """
    t = float(np.clip(tint, -1.0, 1.0))
    w = float(np.clip(temperature, -1.0, 1.0))
    if t == 0.0 and w == 0.0:
        return (1.0, 1.0, 1.0)          # exact identity, not merely close
    k = _TINT_SPREAD
    g = np.array([1.0 + 0.5 * k * t + k * w,
                  1.0 - 0.5 * k * t,
                  1.0 + 0.5 * k * t - k * w], dtype=np.float64)
    g = g / float((g * _LUM_WEIGHTS).sum())
    return (float(g[0]), float(g[1]), float(g[2]))


def apply_tint(img: AstroImage, tint: float, temperature: float) -> AstroImage:
    """Shift the colour cast along green<->magenta and cool<->warm."""
    gains = tint_gains(tint, temperature)
    if not img.is_color or gains == (1.0, 1.0, 1.0):
        return img.copy()
    out = img.data.astype(np.float32) * np.asarray(gains, dtype=np.float32)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def remove_green(img: AstroImage, strength: float = 1.0) -> AstroImage:
    """SCNR green removal: reduce green where it exceeds the red/blue average,
    scaled by `strength` (0 = none, 1 = full average-neutral clamp). Red and blue
    are never touched; mono is unchanged. strength 1.0 reproduces the classic
    `G = min(G, (R+B)/2)` clamp."""
    if not img.is_color:
        return img.copy()
    out = _suppress_green_excess(img.data, float(np.clip(strength, 0.0, 1.0)))
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def _suppress_green_excess(data: np.ndarray, strength: float) -> np.ndarray:
    """Reduce green where it exceeds the red/blue average, scaled by `strength`.
    Red and blue are never modified. Returns a new float32 array. Non-3-channel
    input is returned unchanged (no green channel to fix)."""
    out = data.astype(np.float32).copy()
    if out.ndim != 3 or out.shape[-1] < 3:
        return out
    avg_rb = (out[..., 0] + out[..., 2]) / 2.0
    excess = np.maximum(out[..., 1] - avg_rb, 0.0)
    out[..., 1] = out[..., 1] - float(strength) * excess
    return out


def remove_green_fringe(starless: AstroImage, stars: AstroImage,
                        strength: float) -> AstroImage:
    """De-green the stars layer (green-excess suppression) and screen-recombine
    with the untouched starless background — so only stars change and the
    background/nebula colour is preserved. `strength` 0 = plain recombine."""
    strength = float(np.clip(strength, 0.0, 1.0))
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    if strength > 0.0:
        st = _suppress_green_excess(st, strength)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))


def remove_green_fringe_masked(img: AstroImage, mask: np.ndarray,
                               strength: float) -> AstroImage:
    """Free-path green-fringe removal (no StarXTerminator): suppress green excess
    directly on the image, blended by a feathered star-neighbourhood `mask`, so
    only the region around stars is de-greened and the nebula/background colour is
    preserved. The free split can't isolate a broad chromatic halo into a stars
    layer (a smooth halo is absorbed into the median background), so the
    stars-layer de-green of `remove_green_fringe` barely touches real fringe —
    de-greening in place inside the star mask does. `strength` 0 = unchanged."""
    strength = float(np.clip(strength, 0.0, 1.0))
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    if strength <= 0.0 or not img.is_color or mask is None or float(mask.max()) <= 0.0:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
    degreened = _suppress_green_excess(data, strength)
    m = mask[..., None]
    out = (1.0 - m) * data + m * degreened
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def _background_mask(lum: np.ndarray) -> np.ndarray:
    """Boolean mask of 'empty sky' pixels — above the noise floor, below the
    nebula and stars — so the colour estimate isn't contaminated by real signal.
    Falls back to the darkest 40% if the band is too small."""
    lo, hi = np.percentile(lum, [10.0, 40.0])
    mask = (lum >= lo) & (lum <= hi)
    if int(mask.sum()) < 100:
        mask = lum <= float(np.percentile(lum, 40.0))
    return mask


def background_neutralize(data: np.ndarray) -> np.ndarray:
    """Make the sky background colour-neutral without touching real nebulosity.

    Estimate each channel's background level from a robust low-percentile 'sky'
    sample (so a red/teal nebula filling much of the frame can't skew it), then
    apply a multiplicative, green-anchored gain so the backgrounds match. Because
    the reference is *empty sky* (which truly should be grey) rather than the
    whole-frame average, the dominant nebula colour is preserved — unlike a
    grey-world balance, which would desaturate it and cast the sky the
    complementary colour. Multiplicative gains keep the data linear.
    """
    lum = data.mean(axis=2)
    mask = _background_mask(lum)
    bg = np.array([float(np.median(data[..., c][mask])) for c in range(3)],
                  dtype=np.float32)
    ref = bg[1]  # anchor to green (2× sampled on the GRBG sensor, least noisy)
    gain = (ref / np.clip(bg, 1e-6, None)).astype(np.float32)
    out = data * gain
    return np.clip(out, 0.0, 1.0)


def apply_color(img: AstroImage, settings: ColorSettings) -> AstroImage:
    if not img.is_color:
        return img.copy()  # nothing to balance on a single channel

    data = img.data.astype(np.float32).copy()

    if settings.neutralize_background:
        data = background_neutralize(data)

    result = AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
    # Tint AFTER the background neutralise, so the user's move is relative to a
    # neutral sky rather than fighting whatever cast the sky started with.
    result = apply_tint(result, getattr(settings, "tint", 0.0),
                        getattr(settings, "temperature", 0.0))
    if settings.remove_green:
        result = remove_green(result)
    return result
