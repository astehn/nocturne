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


# Full effect over 60-180 deg — green THROUGH CYAN — ramping in from 36 and out
# to 204.
#
# It was Photoshop's "Greens" range (75/105/135/165) until 2026-09-19, chosen by
# eye against a StarX stars layer. That band was too narrow for the defect it
# exists to fix. Andreas, after three passes at this tool: *"the tool still does
# nothing for my images"* — and it was right not to, because his stars are not
# green, they are TEAL, and teal sat outside the band entirely.
#
# Two separate things had to move, which is why widening once did not help:
#   * the OUTER edge, so cyan is selected at all; and
#   * the PLATEAU, because an edge-only widening left a teal star on the ramp at
#     44% strength — less teal, not neutral.
# Measured on his NGC 281 dualband master, committed mean absolute change:
# 0.000260 before, 0.001675 edge-only, 0.003293 with the plateau moved.
#
# Stars are never green AND never cyan: the blackbody locus runs red-orange-
# yellow-white-blue and passes through neither. So both are artefacts, and both
# are safe to drain. True blue is NOT reached — 204 deg stops well short of it.
_GREEN_BAND = (36.0, 60.0, 190.0, 214.0)
# The same band expressed as |t|, t = (hue - 120) / 60 — see _green_weight for
# why that substitution is exact. Derived rather than written out so the band
# above stays the single definition: hard-coding 0.75/0.25 next to it left a
# constant that documented the code without controlling it.
# The symmetry-about-120 check that used to live here is GONE (2026-09-19). It
# existed to license the `t = (B-R)/span` substitution, which needed the band to
# be symmetric; the hue is computed explicitly now, and the band is deliberately
# NOT symmetric — it reaches for cyan and not for yellow, because cyan is the
# defect and yellow stars are real. What replaces it is the invariant that
# actually matters, checked in the same eager way for the same reason (`python
# -O` strips asserts and the shipped .app is where a quiet guard hurts):
# the band must stop short of true blue.
if not (_GREEN_BAND[0] < _GREEN_BAND[1] < _GREEN_BAND[2] < _GREEN_BAND[3]):
    raise ValueError("_GREEN_BAND corners must ascend")
if _GREEN_BAND[3] > 220.0:
    raise ValueError("_GREEN_BAND must stop short of blue stars (220 deg)")


def _green_weight(rgb: np.ndarray) -> np.ndarray:
    """Per-pixel 0..1 "this pixel reads green-to-cyan", from `_GREEN_BAND`.

    THE HUE IS COMPUTED, not substituted. Until 2026-09-19 this used the
    shortcut hue = 120 + 60*(B-R)/span, which is exact ONLY while green is the
    largest channel — and the old band never left that arc, so it was correct.
    Widening to cyan leaves it: once blue is the maximum and red the minimum,
    (B-R)/span is pinned at exactly 1.0 whatever green does, so cyan and deep
    blue become the same number and a band reaching cyan drains blue stars too.
    Measured before this was fixed: a blue star scored 100%.

    So the two arcs are computed separately, which is two `where`s rather than
    the boolean fancy indexing that made the original literal version slow.

    Red-maximum pixels score zero without being evaluated: `g >= r` is what
    protects orange and yellow stars, and it must stay.

    Neutral pixels have no hue and score 0, so a grey or black frame is
    untouched without needing a separate guard.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    span = mx - mn
    lit = span > 1e-9
    d = np.where(lit, span, 1.0)
    # 60..180 where green leads, 180..300 where blue leads. Nothing else can
    # land inside the band, so red-maximum pixels need no branch of their own.
    hue = np.where(g >= b, 120.0 + 60.0 * (b - r) / d,
                           240.0 + 60.0 * (r - g) / d)
    lo_out, lo_in, hi_in, hi_out = _GREEN_BAND
    w = np.minimum((hue - lo_out) / (lo_in - lo_out),
                   (hi_out - hue) / (hi_out - hi_in))
    return np.clip(w, 0.0, 1.0) * (lit & (g >= r))


# Below this luminance, a stars-layer pixel is noise rather than a star.
#
# The stars layer is NOT only stars: it is everything the split did not put in
# the starless frame, which includes the high-frequency noise speckle. Measured
# on a real NGC 281 master, 2026-09-19 — without a floor, only 15.5% of the
# pixels this step changed were on or beside a star core, and ~65% were not near
# a star at all. Andreas spotted it on screen before any measurement did:
# *"are you absolutely, 100% sure that this only affects stars?"*
#
# IT IS A MODEST HELP, NOT A SOLUTION, and the honest numbers are these —
# measured against this implementation on that master, as a share of the total
# change on star pixels versus everywhere else:
#
#     floor   on-star kept   off-star kept
#     0.02        99.9%          87.4%
#     0.05        99.2%          75.6%
#     0.20        84.7%          42.5%
#     0.35        65.5%          23.5%
#
# So 0.05 buys a quarter less background change for under 1% of the star
# correction, and beyond that the trade turns bad fast. An earlier estimate of
# "two thirds off-star for 0.7% on-star" was wrong: it summed WEIGHTS against a
# channel mean rather than measuring the committed effect. Faint stars and noise
# speckle overlap in brightness, so brightness cannot cleanly separate them and
# no threshold here ever will.
#
# THE REAL FIX IS UPSTREAM and is Andreas's: De-green Stars runs BEFORE Noise
# Reduction, so the noise it sifts through has not been reduced yet. Move the
# step after NR and most of this disappears at the source. Filed; this floor is
# the cheap half.
#
# A brightness floor rather than a star mask on purpose: the mask this tool used
# to carry was removed for good reasons, and "is this bright enough to be a
# star" needs no spatial search.
_STAR_FLOOR = 0.05


def _desaturate_greens(data: np.ndarray, strength: float,
                       floor: float = 0.0) -> np.ndarray:
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
    w = _green_weight(rgb) * float(strength)
    # Rec.709 luma for the floor as well as for the landing colour, so "how
    # bright is this pixel" has exactly one meaning in this function.
    lum1 = rgb @ _LUM_WEIGHTS.astype(np.float32)
    if floor > 0.0:
        w = w * (lum1 >= float(floor))
    w = w[..., None]
    # Rec.709 luma, so a de-greened fringe keeps the brightness it had and star
    # size/brightness does not move — "green becomes white", not "green is
    # deleted" (which is what SCNR's clamp to the red/blue average does).
    out[..., :3] = (1.0 - w) * rgb + w * lum1[..., None]
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
        st = _desaturate_greens(st, strength, floor=_STAR_FLOOR)
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
