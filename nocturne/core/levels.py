from __future__ import annotations

from typing import NamedTuple

import numpy as np

from .image import AstroImage


def apply_levels(img: AstroImage, black: float, gamma: float, white: float,
                 offsets=None) -> AstroImage:
    """Levels adjustment: remap [black, white] to [0, 1] then apply midtone gamma.

    Built in place after the first allocation, and the identity gamma is
    skipped. `np.power(x, 1.0)` is a whole-array pass that returns x exactly —
    measured 19 ms of the 72 ms compose on an 8.3 MP frame — and Starless
    Levels, which runs this on every debounced preview tick, always passes 1.0.
    The result is a FRESH array in both branches (np.subtract allocates it),
    so no caller can find itself aliasing the source.

    `offsets` (red, green, blue) move ONE colour's black point: channel c uses
    black + offsets[c], which may go below 0 and then LIFTS that colour's floor.
    Ignored on a mono picture. All-zero takes the original scalar path, so an
    option without offsets is bit-identical to every build before them.
    """
    if offsets is not None and img.data.ndim == 3 and img.data.shape[2] == 3 \
            and any(float(d) != 0.0 for d in offsets):
        return _apply_levels_per_channel(img, black, gamma, white, offsets)
    white = max(white, black + 1e-4)
    out = np.subtract(img.data, black)          # the one allocation
    out /= (white - black)                      # a division, NOT a reciprocal
    np.clip(out, 0.0, 1.0, out=out)             # multiply: they differ by a ULP
    if gamma != 1.0:
        out = np.power(out, 1.0 / max(gamma, 1e-3))
    return AstroImage(out.astype(np.float32, copy=False),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def _apply_levels_per_channel(img, black, gamma, white, offsets) -> AstroImage:
    """The scalar path with one black per channel. The per-channel numbers are
    computed in float64 exactly as the scalar path computes its one number,
    then handed to float32 arithmetic as the scalar is — so a channel whose
    offset is 0 comes out bit-identical to the scalar path's."""
    blacks = [float(black) + float(d) for d in offsets]
    whites = [max(white, b + 1e-4) for b in blacks]
    b32 = np.array(blacks, dtype=np.float64).astype(img.data.dtype)
    span = np.array([w - b for w, b in zip(whites, blacks)],
                    dtype=np.float64).astype(img.data.dtype)
    out = np.subtract(img.data, b32)
    out /= span
    np.clip(out, 0.0, 1.0, out=out)
    if gamma != 1.0:
        out = np.power(out, 1.0 / max(gamma, 1e-3))
    return AstroImage(out.astype(np.float32, copy=False),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


# Black point = median - _BLACK_SIGMA * MAD, the same robust shape autostretch
# uses. Not autostretch's 2.8, because the two run on different data: 2.8 clips
# the LINEAR frame before a midtone transfer, while this runs after the stretch
# has already compressed everything upward.
#
# 3.5 measured across six real masters (M 45, M 31 mosaic, M 8, M 16, NGC 7000,
# NGC 281). It was 4.0 first, and 3.5 beat it on two independent grounds:
#
#   * It matches Andreas. On M 45 he set 0.07 by hand where 4.0 suggested 0.055;
#     3.5 gives 0.081. Two data points is not a calibration, but the direction
#     was consistent and the cost of following it is bounded below.
#   * It ends a dead button. At 4.0 the black point on M 16 came out exactly
#     0.0 — a nebula-filled frame whose MAD is large relative to its median — so
#     Auto Levels did nothing at all there. 3.5 gives 0.0256.
#
# The floor is black clipping, which is what rules out going further: at 3.5 it
# stays at or under 0.54% (M 8 the worst); at 3.0 M 8 reaches 0.98% and at 2.8
# 1.25%, which eats faint nebulosity. M 31's 11.7% is its empty mosaic border
# and does not move with sigma.
AUTO = "auto"
"""The Levels option meaning "re-derive from the image in front of you".

Lives here, in the module both the recipe layer and the step already
import, so the two cannot drift: three separate copies of a magic string
with nothing asserting they are equal is a rename waiting to fail
silently. `steps/levels.py` importing `recipe` would risk a cycle."""

_BLACK_SIGMA = 3.5


def auto_levels(data: np.ndarray) -> tuple[float, float, float]:
    """Suggested (black, gamma, white) for a STRETCHED image.

    Sets a black point and nothing else, because after a stretch there is
    nothing else left to set automatically — and both of the other two used to
    do active harm:

    * **Gamma is 1.0.** autostretch deliberately places the background at
      `_TARGET_BG` (0.25); this function used to re-target 0.35 with an adaptive
      gamma, so two steps disagreed about sky brightness and the later one won.
      Measured, it lifted the sky +12% to +30% on every real master. That is the
      "milky" look Andreas rejected. `auto_enhance` had already diagnosed this
      and worked around it locally by discarding the gamma; the manual Levels
      step kept the defect.
    * **White is 1.0.** The stretch already maps the data into [0, 1] with star
      cores at the top, so a percentile white point can only clip stars or
      brighten the frame. The old 99.9th percentile drove ~0.08% of pixels to
      pure white on every master — roughly 6,000 star cores, whose colour is
      real data, since Seestar cores do not saturate in the capture. Raising it
      to 99.99% did not fix it either: on M 16 that percentile is 0.889 against
      a maximum of 0.999, so it BRIGHTENED the sky 0.2013 -> 0.2264, smuggling
      the lift back in through the other end.

    MAD and not a percentile, which is the part that matters on a mosaic: 11.59%
    of Andreas' real M 31 mosaic is empty border outside panel coverage, so the
    old 1st percentile landed inside the border and returned exactly 0.0 — the
    black point silently did nothing on every mosaic he made. The robust
    estimator reads 0.1431 on that same frame and never sees the border.

    nanmedian for the reason `autostretch._stretch_params` documents: these are
    two scalars derived from the whole frame, and with plain `np.median` one NaN
    makes both NaN, which then blanks every pixel.
    """
    lum = data.mean(axis=2) if data.ndim == 3 else data
    if not np.isfinite(lum).any():
        return 0.0, 1.0, 1.0            # no statistics to derive from
    med = float(np.nanmedian(lum))
    mad = float(np.nanmedian(np.abs(lum - med)))
    black = float(np.clip(med - _BLACK_SIGMA * mad, 0.0, 0.5))
    return black, 1.0, 1.0


# --- Auto, version 2: stop at the clipping warning --------------------------
#
# Measured on 14 of Andreas' projects (2026-10-14, Stretch v2 then Auto):
# version 1 pushed 12/14 into the read-out's amber, typically 0.5-1.5% crushed
# in R and B with G ~0 — one shared black point crushes R and B >=5x more than
# G. Version 2 keeps version 1's black as the CANDIDATE and takes the largest
# black at or below it that turns no channel amber by itself and makes no
# already-amber channel worse. Gamma and white stay 1.0.
AUTO_V1 = 1
AUTO_V2 = 2
AUTO_VERSION = AUTO_V2
"""The Auto a fresh press (and a recipe or preset saying "auto") runs. A
saved project's history entry names its version, so a later version can
never change a picture that was already made."""

BLACK_STEPS = 1000
"""Positions on the Black point slider (three decimals). The UI imports it;
Auto's search resolves finer than one of these steps."""

# Bisection stops when the bracket is narrower than a quarter slider step: the
# answer is then within one step of the true largest black, which is what the
# slider can show anyway. ~11 halvings from a 0.5 candidate.
_AUTO_RESOLUTION = 1.0 / (4 * BLACK_STEPS)


class AutoBlack(NamedTuple):
    """What Auto decided. `candidate` is version 1's black (median - 3.5 MAD);
    `stopped` is True only when version 2 came in below it — the one case the
    panel and the log explain."""

    black: float
    candidate: float
    stopped: bool


class CrushProbe:
    """Per-channel structural crushed figure of `apply_levels(img, ...)`, as
    the clipping read-out would measure it — without rendering the frame.

    Exactly `structural_channel_clipping(display_rgb8(apply_levels(img, ...))).lo`
    for a non-linear picture (a test holds the two equal): the read-out's own
    blocks and sampling (`structural_block_peaks`), the same `apply_levels`,
    the same 8-bit cast (`display_rgb8`). Only the peaks are re-mapped per
    query, which is what makes Auto's search cheap on a 33 MP frame."""

    def __init__(self, img: AstroImage) -> None:
        from .inspect import structural_block_peaks
        peaks = structural_block_peaks(img.data)
        self.channels = 0 if peaks is None else peaks.shape[2]
        # Mono back to 2-D, so display_rgb8 greys it to RGB as it does the frame.
        self._peaks = peaks[:, :, 0] if self.channels == 1 else peaks

    def crushed(self, black: float = 0.0, gamma: float = 1.0, white: float = 1.0,
                offsets=None) -> tuple[float, ...]:
        """Fraction (0-1) of structural blocks crushed to 0, per channel."""
        if self._peaks is None:
            return ()
        from .export import display_rgb8
        mapped = apply_levels(AstroImage(self._peaks, is_linear=False),
                              black, gamma, white, offsets)
        rgb = display_rgb8(mapped)          # mono peaks come back as grey RGB
        dead = (rgb == 0).reshape(-1, 3).mean(axis=0)
        return tuple(float(v) for v in dead[:1 if self.channels == 1 else 3])


def auto_black(img: AstroImage, version: int = AUTO_VERSION) -> AutoBlack:
    """Auto's black point for `img`, in the given version.

    Version 1 is `auto_levels` as it always was. Version 2 bisects on the
    black in [0, candidate] — the crushed figure only grows with the black, so
    the passing set is an interval from 0 — for the largest black at which
    every channel is under `CRUSHED_LIMIT` or no worse than it arrived. At or
    over the limit counts as over, because that is where the read-out turns
    amber. A LINEAR picture has no structural read-out to stay under (it is
    autostretched for display), so it keeps the candidate.
    """
    candidate = float(auto_levels(img.data)[0])
    if int(version) == AUTO_V1 or candidate <= 0.0 or img.is_linear:
        return AutoBlack(candidate, candidate, False)
    from .inspect import CRUSHED_LIMIT
    probe = CrushProbe(img)
    if probe.channels == 0:
        return AutoBlack(candidate, candidate, False)
    arrived = probe.crushed()

    def ok(b: float) -> bool:
        return all(now < CRUSHED_LIMIT or now <= was
                   for now, was in zip(probe.crushed(b), arrived))

    if ok(candidate):
        return AutoBlack(candidate, candidate, False)
    lo, hi = 0.0, candidate                 # ok(0) holds: identity == arrival
    while hi - lo > _AUTO_RESOLUTION:
        mid = 0.5 * (lo + hi)
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return AutoBlack(lo, candidate, True)


# --- the history option -----------------------------------------------------
#
# Shapes a Levels option has had, all still read:
#   (b, g, w) tuple / [b, g, w] list    manual, before colour offsets
#   "auto"                              Auto version 1 IN A SAVED PROJECT
#                                       (a recipe or preset "auto" is turned
#                                       into the current Auto by recipe.py)
#   "" / None                           identity
#   {"auto": True, "version": 2, "offsets": [r, g, b]}
#   {"black": b, "gamma": g, "white": w, "offsets": [r, g, b]}
_ZERO_OFFSETS = (0.0, 0.0, 0.0)


class LevelsParams(NamedTuple):
    auto: bool
    version: int            # meaningful only when auto
    black: float            # ignored when auto: re-derived from the image
    gamma: float
    white: float
    offsets: tuple          # (red, green, blue) added to the black point


def _offsets_of(value) -> tuple:
    try:
        r, g, b = value
        return (float(r), float(g), float(b))
    except (TypeError, ValueError):
        return _ZERO_OFFSETS


def parse_levels_option(option) -> LevelsParams:
    """Every shape a Levels option has had, as one value."""
    if option == AUTO:
        return LevelsParams(True, AUTO_V1, 0.0, 1.0, 1.0, _ZERO_OFFSETS)
    if isinstance(option, dict):
        offsets = _offsets_of(option.get("offsets", _ZERO_OFFSETS))
        if option.get("auto"):
            try:
                version = int(option.get("version", AUTO_V1))
            except (TypeError, ValueError):
                version = AUTO_V1
            return LevelsParams(True, version, 0.0, 1.0, 1.0, offsets)
        return LevelsParams(False, AUTO_V1, float(option.get("black", 0.0)),
                            float(option.get("gamma", 1.0)),
                            float(option.get("white", 1.0)), offsets)
    if isinstance(option, (tuple, list)) and len(option) == 3:
        b, g, w = option
        return LevelsParams(False, AUTO_V1, float(b), float(g), float(w), _ZERO_OFFSETS)
    return LevelsParams(False, AUTO_V1, 0.0, 1.0, 1.0, _ZERO_OFFSETS)


def new_levels_option(black: float = 0.0, gamma: float = 1.0, white: float = 1.0,
                      offsets=_ZERO_OFFSETS, *, auto: bool = False) -> dict:
    """The option for a Levels step made NOW. Auto records the current version,
    so a later version cannot change it on replay; a manual one records its
    three numbers. Both carry the colour offsets."""
    offs = [float(v) for v in _offsets_of(offsets)]
    if auto:
        return {"auto": True, "version": AUTO_VERSION, "offsets": offs}
    return {"black": float(black), "gamma": float(gamma), "white": float(white),
            "offsets": offs}


def levels_option_dict(option) -> dict | None:
    """A dict-shaped option in its canonical form (the shape
    `new_levels_option` writes, keeping its recorded version), or None for the
    legacy tuple/"auto" shapes, which are stored as they always were."""
    if not isinstance(option, dict):
        return None
    p = parse_levels_option(option)
    if p.auto:
        return {"auto": True, "version": p.version, "offsets": list(p.offsets)}
    return {"black": p.black, "gamma": p.gamma, "white": p.white,
            "offsets": list(p.offsets)}


class ResolvedLevels(NamedTuple):
    black: float
    gamma: float
    white: float
    offsets: tuple
    auto: AutoBlack | None   # what Auto decided, when the option was Auto


def resolve_levels(img: AstroImage, option) -> ResolvedLevels:
    """The numbers `option` means on `img`: Auto re-derived in its recorded
    version, manual as stored. The step applies exactly these, and a preview
    that wants to equal the step calls this too."""
    p = parse_levels_option(option)
    if p.auto:
        a = auto_black(img, p.version)
        return ResolvedLevels(a.black, 1.0, 1.0, p.offsets, a)
    return ResolvedLevels(p.black, p.gamma, p.white, p.offsets, None)


_OFFSET_WORDS = ("red", "green", "blue")


def describe_offsets(offsets) -> str:
    """"blue −0.015" — the colours moved, in the panel's three decimals and a
    true minus sign; "" when none moved."""
    parts = []
    for word, d in zip(_OFFSET_WORDS, _offsets_of(offsets)):
        if d != 0.0:
            parts.append(f"{word} {d:+.3f}".replace("-", "\u2212"))
    return ", ".join(parts)
