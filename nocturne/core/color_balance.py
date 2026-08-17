from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage

TONES = ("shadows", "midtones", "highlights")

# How far a slider at full travel moves a channel, at the tone's peak weight.
# ONE scalar shared by all three axes, not one per channel: equal slider values
# must move equal amounts or the axes cannot be compared to each other.
#
# 0.10 means full travel moves a midtone channel by ~26 of 255 levels — strong
# but not destructive. Calibrated on the M 31 mosaic against the settings
# Andreas uses in Photoshop (Midtones, Cyan/Red -18, Yellow/Blue +20, preserve
# luminosity, 80% opacity), measured as the change in blue/red ratio over the
# masked galaxy:
#
#     MAX_SHIFT   B/R change
#         0.05        +4.3%
#         0.10        +8.8%     <- chosen
#         0.15       +13.4%
#         0.25       +23.2%
#         0.40       +39.4%
#
# 0.15 was the initial guess and is visibly too strong for a quarter-travel
# slider: it would make full travel a ~55% swing.
MAX_SHIFT = 0.10

# Above this fraction of the frame, skipping unselected pixels costs more than
# it saves — see the gate in apply_balance.
_SPARSE_MAX = 0.5


@dataclass(frozen=True)
class Balance:
    """A Color Balance adjustment: the familiar opposed pairs, per tonal range.

    The axes are named for the channel they add to, so `red = -1` is full Cyan
    and `red = +1` is full Red — the same convention as the slider labels.
    """

    tone: str = "midtones"
    red: float = 0.0            # Cyan   <-> Red
    green: float = 0.0          # Magenta <-> Green
    blue: float = 0.0           # Yellow <-> Blue
    preserve_lum: bool = True
    strength: float = 1.0       # the equivalent of a layer's opacity


def tone_weight(lum: np.ndarray, tone: str) -> np.ndarray:
    """How strongly each luminance is affected, for one tonal range."""
    x = np.clip(np.asarray(lum, dtype=np.float32), 0.0, 1.0)
    if tone == "shadows":
        return (np.clip(1.0 - 2.0 * x, 0.0, 1.0) ** 2).astype(np.float32)
    if tone == "highlights":
        return (np.clip(2.0 * x - 1.0, 0.0, 1.0) ** 2).astype(np.float32)
    if tone == "midtones":
        return (4.0 * x * (1.0 - x)).astype(np.float32)
    raise ValueError(f"unknown tone: {tone!r} (expected one of {TONES})")


def apply_balance(img: AstroImage, b: Balance,
                  mask: np.ndarray | None = None) -> AstroImage:
    """Shift colour within a tonal range, optionally confined by `mask`.

    The order is shift, preserve luminosity, then blend by mask x strength —
    the same order a Photoshop adjustment layer uses, where the adjustment is
    computed whole and then composited at the layer's opacity.

    The design claimed this order was numerically critical and that the reverse
    would leave a halo across the feathered edge. It measured false: on
    real-shaped data the two orders differ by 0.01 of one 8-bit level. Matching
    the layer model is the reason to keep it; the halo was not real.
    """
    if img.data.ndim != 3:
        raise ValueError("Colour balance needs a colour image")
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    amounts = np.array([b.red, b.green, b.blue], dtype=np.float32)
    strength = float(np.clip(b.strength, 0.0, 1.0))

    if strength == 0.0 or not amounts.any():
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    if mask is None:
        return AstroImage(_blended(data, data, amounts, b, strength),
                          is_linear=img.is_linear, metadata=dict(img.metadata))

    # Work only where the mask actually selects something. Everywhere else the
    # blend multiplies the shift by zero and throws it away, so computing it is
    # pure waste — and it is not small waste: preserving luminosity converts to
    # CIE Lab and back, which on the 39.5 Mpx M 31 mosaic took 4.5 s of a 7.6 s
    # Apply while the mask selected 2.11% of the frame. Exact, not approximate:
    # the discarded pixels are unchanged either way.
    m = np.clip(mask, 0.0, 1.0).astype(np.float32)
    sel = m > 0.0
    frac = float(sel.mean())
    if frac == 0.0:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
    if frac > _SPARSE_MAX:
        # Gathering and scattering costs more than it saves once most of the
        # frame is selected: measured on the 39.5 Mpx mosaic, the whole-image
        # case went 7.6 s -> 10.5 s before this gate existed. The saving only
        # exists when there is genuinely something to skip.
        return AstroImage(_blended(data, data, amounts, b, strength, m[..., None]),
                          is_linear=img.is_linear, metadata=dict(img.metadata))

    out = data.copy()
    patch = data[sel][:, None, :]                       # (N, 1, 3) keeps Lab happy
    shifted = _blended(patch, patch, amounts, b, strength, m[sel][:, None, None])
    out[sel] = shifted[:, 0, :]
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def _blended(data: np.ndarray, ref: np.ndarray, amounts: np.ndarray,
             b: Balance, strength: float, mask=None) -> np.ndarray:
    """Shift, preserve luminosity, blend — on whatever slice it is handed."""
    w = tone_weight(ref.mean(axis=-1), b.tone)[..., None]
    shifted = np.clip(data + amounts * MAX_SHIFT * w, 0.0, 1.0)
    if b.preserve_lum:
        from .narrowband import preserve_lightness
        shifted = preserve_lightness(shifted, data)
    blend = strength if mask is None else mask * strength
    return np.clip(data + (shifted - data) * blend, 0.0, 1.0).astype(np.float32)
