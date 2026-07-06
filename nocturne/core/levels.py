from __future__ import annotations

import numpy as np

from .image import AstroImage


def apply_levels(img: AstroImage, black: float, gamma: float, white: float) -> AstroImage:
    """Levels adjustment: remap [black, white] to [0, 1] then apply midtone gamma."""
    white = max(white, black + 1e-4)
    x = np.clip((img.data - black) / (white - black), 0.0, 1.0)
    out = np.power(x, 1.0 / max(gamma, 1e-3))
    return AstroImage(
        out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata)
    )
