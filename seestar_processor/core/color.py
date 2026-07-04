from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage


@dataclass
class ColorSettings:
    neutralize_background: bool = True
    white_balance: bool = True
    remove_green: bool = False


def remove_green(img: AstroImage) -> AstroImage:
    """SCNR (average neutral): clamp green to the red/blue average. Mono unchanged."""
    if not img.is_color:
        return img.copy()
    data = img.data.astype(np.float32).copy()
    avg_rb = (data[..., 0] + data[..., 2]) / 2.0
    data[..., 1] = np.minimum(data[..., 1], avg_rb)
    return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))


def apply_color(img: AstroImage, settings: ColorSettings) -> AstroImage:
    if not img.is_color:
        return img.copy()  # nothing to balance on a single channel

    data = img.data.astype(np.float32).copy()

    if settings.neutralize_background:
        # Align each channel's background (median) to the lowest channel so the
        # background becomes colour-neutral.
        meds = [float(np.median(data[..., c])) for c in range(3)]
        target = min(meds)
        for c in range(3):
            data[..., c] = np.clip(data[..., c] - (meds[c] - target), 0.0, 1.0)

    if settings.white_balance:
        # Grey-world: scale channels so their means match.
        means = [float(data[..., c].mean()) for c in range(3)]
        gray = float(np.mean(means))
        for c in range(3):
            if means[c] > 1e-6:
                data[..., c] = np.clip(data[..., c] * (gray / means[c]), 0.0, 1.0)

    result = AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))
    if settings.remove_green:
        result = remove_green(result)
    return result
