from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage

_SATURATION = {"None": 1.0, "Subtle": 1.15, "Medium": 1.35, "Strong": 1.7}
SATURATION_LEVELS = list(_SATURATION)
SKY_LEVELS = ["Darker", "Normal", "Lighter"]


@dataclass
class FinalFixesSettings:
    remove_green: bool = False
    saturation: str = "None"
    increase_blue: bool = False
    sky: str = "Normal"


def _apply_sky(data: np.ndarray, sky: str) -> np.ndarray:
    if sky == "Darker":
        return np.clip((data - 0.05) / 0.95, 0.0, 1.0)
    if sky == "Lighter":
        return np.clip(data ** 0.85, 0.0, 1.0)
    return data


def apply_final_fixes(img: AstroImage, settings: FinalFixesSettings) -> AstroImage:
    data = img.data.astype(np.float32).copy()

    if img.is_color:
        if settings.remove_green:
            # SCNR (average neutral): clamp green to the red/blue average.
            avg_rb = (data[..., 0] + data[..., 2]) / 2.0
            data[..., 1] = np.minimum(data[..., 1], avg_rb)

        factor = _SATURATION.get(settings.saturation, 1.0)
        if factor != 1.0:
            lum = data.mean(axis=2, keepdims=True)
            data = np.clip(lum + (data - lum) * factor, 0.0, 1.0)

        if settings.increase_blue:
            data[..., 2] = np.clip(data[..., 2] * 1.1, 0.0, 1.0)

    data = _apply_sky(data, settings.sky)

    return AstroImage(
        np.clip(data, 0.0, 1.0).astype(np.float32),
        is_linear=img.is_linear,
        metadata=dict(img.metadata),
    )
