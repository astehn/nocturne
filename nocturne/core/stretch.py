from __future__ import annotations

import numpy as np

from .autostretch import linked_stretch
from .image import AstroImage

# Slider amount [0, 1] maps to a target background-median brightness. Mid-slider
# (~0.5) lands near the display preview's target (0.25), so "what you preview is
# what you get"; higher = more aggressive reveal of faint detail.
_TARGET_MIN = 0.10
_TARGET_MAX = 0.45


def amount_to_target(amount: float) -> float:
    a = min(1.0, max(0.0, float(amount)))
    return _TARGET_MIN + a * (_TARGET_MAX - _TARGET_MIN)


def apply_stretch(img: AstroImage, amount: float) -> AstroImage:
    """Adaptive nonlinear stretch (linear -> display). `amount` in [0, 1] is the
    aggressiveness; the stretch measures the image so faint signal is lifted."""
    out = linked_stretch(img.data, amount_to_target(amount))
    return AstroImage(out.astype(np.float32), is_linear=False, metadata=dict(img.metadata))
