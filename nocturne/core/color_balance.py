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
    """A Color Balance adjustment: independent amounts for EACH tonal range.

    Each field is an (r, g, b) triple on the familiar opposed pairs — Cyan/Red,
    Magenta/Green, Yellow/Blue — named for the channel it adds to, so -1 is full
    Cyan and +1 is full Red.

    All three ranges live in ONE adjustment, which is how Photoshop's Color
    Balance behaves: switching its Tone radio preserves each range's sliders.
    The first version here carried a single `tone` plus one triple, so pushing
    highlights blue and midtones red at once was impossible — the limitation
    Andreas hit immediately in real use.

    Stacking cannot overshoot: the three tone weights partition unity at every
    luminance (verified in the tests), so three full-travel ranges in the same
    direction move a channel by at most MAX_SHIFT — exactly what one does.
    """

    shadows: tuple[float, float, float] = (0.0, 0.0, 0.0)
    midtones: tuple[float, float, float] = (0.0, 0.0, 0.0)
    highlights: tuple[float, float, float] = (0.0, 0.0, 0.0)
    preserve_lum: bool = True
    strength: float = 1.0       # the equivalent of a layer's opacity

    def amounts(self, tone: str) -> tuple[float, float, float]:
        if tone not in TONES:
            raise ValueError(f"unknown tone: {tone!r} (expected one of {TONES})")
        return getattr(self, tone)

    def is_neutral(self) -> bool:
        return not any(any(self.amounts(t)) for t in TONES)


def single_tone(tone: str, red: float = 0.0, green: float = 0.0, blue: float = 0.0,
                **kw) -> Balance:
    """A Balance affecting one tonal range only.

    Convenience for callers and tests, and the shape every adjustment saved
    before per-tone amounts existed had — so it doubles as the migration path.
    """
    if tone not in TONES:
        raise ValueError(f"unknown tone: {tone!r} (expected one of {TONES})")
    return Balance(**{tone: (float(red), float(green), float(blue))}, **kw)


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
    strength = float(np.clip(b.strength, 0.0, 1.0))

    if strength == 0.0 or b.is_neutral():
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    if mask is None:
        return AstroImage(_blended(data, data, b, strength),
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
        return AstroImage(_blended(data, data, b, strength, m[..., None]),
                          is_linear=img.is_linear, metadata=dict(img.metadata))

    out = data.copy()
    patch = data[sel][:, None, :]                       # (N, 1, 3) keeps Lab happy
    shifted = _blended(patch, patch, b, strength, m[sel][:, None, None])
    out[sel] = shifted[:, 0, :]
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def _blended(data: np.ndarray, ref: np.ndarray, b: Balance, strength: float,
             mask=None) -> np.ndarray:
    """Shift, preserve luminosity, blend — on whatever slice it is handed.

    The shift is the SUM of all three tonal ranges' contributions, each weighted
    by its own curve over luminance. With two of the three left at zero this is
    exactly the single-range behaviour it replaced.
    """
    lum = ref.mean(axis=-1)
    shift = np.zeros_like(data)
    for tone in TONES:
        amounts = np.asarray(b.amounts(tone), dtype=np.float32)
        if not amounts.any():
            continue
        shift = shift + amounts * MAX_SHIFT * tone_weight(lum, tone)[..., None]
    shifted = np.clip(data + shift, 0.0, 1.0)
    if b.preserve_lum:
        from .narrowband import preserve_lightness
        shifted = preserve_lightness(shifted, data)
    blend = strength if mask is None else mask * strength
    return np.clip(data + (shifted - data) * blend, 0.0, 1.0).astype(np.float32)


def describe(option: dict) -> str:
    """Which ranges an adjustment actually moved, e.g. "midtones, highlights".

    The log line and the provenance report both used to read a single `tone`
    field. Once each range carried its own amounts that key stopped existing,
    and both surfaces silently degraded to nothing — the log said "Colour
    Balance" with no detail and the report lost its headline entirely, with
    nothing to indicate anything was missing.
    """
    moved = [t for t in TONES if any(float(v) for v in (option.get(t) or (0, 0, 0)))]
    if not moved:
        return "no change"
    text = ", ".join(moved)
    return f"{text} (inverted)" if option.get("invert") else text
