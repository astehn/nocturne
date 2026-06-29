from __future__ import annotations

import numpy as np

from .image import AstroImage

STRETCH_PRESETS = ("Small", "Medium", "Large")
_INTENSITY = {"Small": 10.0, "Medium": 50.0, "Large": 200.0}


def apply_stretch(img: AstroImage, preset: str) -> AstroImage:
    if preset not in _INTENSITY:
        raise ValueError(f"unknown preset {preset!r}; expected {STRETCH_PRESETS}")
    a = _INTENSITY[preset]
    x = np.clip(img.data, 0.0, 1.0)
    out = np.arcsinh(a * x) / np.arcsinh(a)
    return AstroImage(out.astype(np.float32), is_linear=False, metadata=dict(img.metadata))
