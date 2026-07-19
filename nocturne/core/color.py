from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .image import AstroImage


@dataclass
class ColorSettings:
    neutralize_background: bool = True
    remove_green: bool = False


def remove_green(img: AstroImage) -> AstroImage:
    """SCNR (average neutral): clamp green to the red/blue average. Mono unchanged."""
    if not img.is_color:
        return img.copy()
    data = img.data.astype(np.float32).copy()
    avg_rb = (data[..., 0] + data[..., 2]) / 2.0
    data[..., 1] = np.minimum(data[..., 1], avg_rb)
    return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))


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
