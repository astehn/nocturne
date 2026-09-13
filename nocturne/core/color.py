from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage


@dataclass
class ColorSettings:
    neutralize_background: bool = True
    remove_green: bool = False
    method: str = "sky"           # "sky" (background balance) or "photometric" (SPCC)


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


# Photoshop's Hue/Saturation "Greens" range: full effect over 105-135 deg,
# ramping in from 75 and out to 165. Not a tuned number of ours — it is the
# exact selection Andreas validated by eye, pulling a StarX stars layer into
# Photoshop and dropping the Greens saturation to zero (2026-09-13).
_GREEN_BAND = (75.0, 105.0, 135.0, 165.0)
# The same band expressed as |t|, t = (hue - 120) / 60 — see _green_weight for
# why that substitution is exact. Derived rather than written out so the band
# above stays the single definition: hard-coding 0.75/0.25 next to it left a
# constant that documented the code without controlling it.
# A raise, not an assert: `python -O` strips asserts, and the shipped .app is
# exactly where a dev-only guard going quiet would hurt.
if ((_GREEN_BAND[1] - _GREEN_BAND[0]) != (_GREEN_BAND[3] - _GREEN_BAND[2])
        or (_GREEN_BAND[1] + _GREEN_BAND[2]) != 240.0):
    raise ValueError("_GREEN_BAND must stay symmetric about pure green (120 deg)")
_T_OUTER = (120.0 - _GREEN_BAND[0]) / 60.0     # 0.75
_T_INNER = (120.0 - _GREEN_BAND[1]) / 60.0     # 0.25


def _green_weight(rgb: np.ndarray) -> np.ndarray:
    """Per-pixel 0..1 "this pixel reads green", equivalent to selecting
    `_GREEN_BAND` by HSV hue but without ever forming the hue angle.

    Two facts collapse it to arithmetic. The band is symmetric about pure green
    (120 deg), and all 90 deg of it sit inside the 60..180 arc where green is
    the largest channel — so a pixel green is not the maximum of cannot score at
    all, and for the rest hue = 120 + 60*(B-R)/span. Writing t for (B-R)/span,
    the band's four corners 75/105/135/165 are just |t| = 0.75/0.25, giving
    `w = clip((_T_OUTER - |t|) / (_T_OUTER - _T_INNER), 0, 1)`.

    Worth the algebra: the literal hue-angle version needed boolean fancy
    indexing over three channel-is-max cases and ran 0.84 s on a 4158x3326
    frame, which is a visible lag on a control whose whole job is to be toggled
    back and forth.

    Neutral pixels have no hue and score 0, so a grey or black frame is
    untouched without needing a separate guard.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    span = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    lit = span > 1e-9
    t = (b - r) / np.where(lit, span, 1.0)
    w = np.clip((_T_OUTER - np.abs(t)) / (_T_OUTER - _T_INNER), 0.0, 1.0)
    # Two parts of this line survive mutation testing because they are
    # redundant, not because they are untested — don't "fix" either one.
    # `abs(t)`: the band is symmetric about pure green, so swapping r and b is
    # an exact no-op. `g >= b`: if g >= r and b > g then r is the minimum, so
    # span is exactly b - r and t is exactly 1.0, which the band already
    # rejects. It stays because "green is the largest channel" is the intent,
    # and one comparison is cheaper than a reader having to prove that.
    return w * (lit & (g >= r) & (g >= b))


def _desaturate_greens(data: np.ndarray, strength: float) -> np.ndarray:
    """Move green pixels to neutral at the same luminance, leaving every other
    hue alone. Returns a new float32 array; non-3-channel input is unchanged.

    This is what "de-green" has to mean on a STARS layer, and it is not what
    SCNR (`_suppress_green_excess`) does. SCNR removes green wherever green
    exceeds the red/blue average, which is true of cyan and yellow-green too,
    so on a stars layer it spends most of its effort dragging correctly
    coloured stars toward magenta. Measured on two real drizzled masters
    (2026-09-13), share of the green SCNR removes that came from pixels whose
    hue actually reads green:

                     green   cyan   yellow
        NGC 281       4.0%   49.5%    9.4%
        IC 1396A      5.6%    2.4%   35.5%

    Selecting by hue instead is also what makes the star mask unnecessary: a
    green fringe, green sky residue and a green nebula pixel are all things
    nobody wants green, and no star is green in the first place (blackbody
    colour runs red-orange-yellow-white-blue and never passes through green),
    so there is nothing to protect by aiming.
    """
    out = data.astype(np.float32).copy()
    if out.ndim != 3 or out.shape[-1] < 3:
        return out
    rgb = out[..., :3]
    w = (_green_weight(rgb) * float(strength))[..., None]
    # Rec.709 luma, so a de-greened fringe keeps the brightness it had and star
    # size/brightness does not move — "green becomes white", not "green is
    # deleted" (which is what SCNR's clamp to the red/blue average does).
    lum = (rgb @ _LUM_WEIGHTS.astype(np.float32))[..., None]
    out[..., :3] = (1.0 - w) * rgb + w * lum
    return out


def remove_green_fringe(starless: AstroImage, stars: AstroImage,
                        strength: float) -> AstroImage:
    """De-green the stars layer and screen-recombine with the untouched starless
    background. `strength` 0 = plain recombine.

    The starless layer is never opened, so nebula colour cannot move: whatever
    OIII or Ha is in the image stays exactly as it was, and the most this can
    reach is the faint ghost of it the split left in the stars layer.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    if strength > 0.0:
        st = _desaturate_greens(st, strength)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))


def remove_green_fringe_masked(img: AstroImage, mask: np.ndarray,
                               strength: float) -> AstroImage:
    """Free-path green-fringe removal (no StarXTerminator): de-green directly on
    the image, blended by a feathered star-neighbourhood `mask`. The free split
    can't isolate a broad chromatic halo into a stars layer (a smooth halo is
    absorbed into the median background), so the stars-layer de-green of
    `remove_green_fringe` barely touches real fringe — de-greening in place
    inside the star mask does. `strength` 0 = unchanged.

    The mask stays here even though `_desaturate_greens` needs no aiming of its
    own, because this path works on the ORIGINAL image, nebula included. The
    StarX path gets its protection from the split (the nebula is in the layer
    it never opens); without a split, the star mask is that protection."""
    strength = float(np.clip(strength, 0.0, 1.0))
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    if strength <= 0.0 or not img.is_color or mask is None or float(mask.max()) <= 0.0:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
    degreened = _desaturate_greens(data, strength)
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
    if settings.remove_green:
        result = remove_green(result)
    return result
