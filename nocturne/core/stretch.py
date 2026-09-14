from __future__ import annotations

import numpy as np

from .autostretch import neutral_stretch, unlinked_stretch
from .image import AstroImage

# Slider amount [0, 1] maps to a target background-median brightness. Mid-slider
# (~0.5) lands near the display preview's target (0.25), so "what you preview is
# what you get"; higher = more aggressive reveal of faint detail.
_TARGET_MIN = 0.10
_TARGET_MAX = 0.45


def amount_to_target(amount: float) -> float:
    a = min(1.0, max(0.0, float(amount)))
    return _TARGET_MIN + a * (_TARGET_MAX - _TARGET_MIN)


def apply_stretch(img: AstroImage, amount: float, *,
                  linked: bool = True) -> AstroImage:
    """Adaptive nonlinear stretch (linear -> display). `amount` in [0, 1] is the
    aggressiveness; the stretch measures the image so faint signal is lifted.

    `linked` picks the MECHANISM, not a second degree of aggressiveness. Linked
    neutralises the background and then applies one curve to every channel;
    unlinked normalises each channel to the target independently, which removes
    a sky-colour cast but also removes any per-channel gain applied earlier —
    including a photometric calibration (measured: SPCC survives an unlinked
    stretch at 0.0004 of an 8-bit level, i.e. not at all).

    Neither is the correct one. The measurement that would settle that is still
    unresolved; the user chooses by eye. See
    docs/superpowers/specs/2026-09-14-linked-unlinked-stretch-design.md.
    """
    out = (neutral_stretch if linked else unlinked_stretch)(
        img.data, amount_to_target(amount))
    return AstroImage(out.astype(np.float32), is_linear=False, metadata=dict(img.metadata))
