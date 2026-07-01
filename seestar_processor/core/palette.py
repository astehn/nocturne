from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .image import AstroImage

PALETTES = ("HOO", "pseudo_SHO")


def extract_channels(img: AstroImage) -> tuple:
    """Return (ha, oiii) as 2D float32 in [0,1]. Ha = red channel; OIII =
    mean of green and blue. Raises ValueError for a non-colour image."""
    if not img.is_color:
        raise ValueError("palette needs a colour (RGB) master")
    data = np.clip(img.data, 0.0, 1.0)
    ha = data[..., 0].astype(np.float32)
    oiii = ((data[..., 1] + data[..., 2]) / 2.0).astype(np.float32)
    return ha, oiii


def subtract_background(img: AstroImage, percentile: float = 50.0) -> AstroImage:
    """Drop each channel's sky pedestal to ~0 by subtracting a per-channel
    background level (a low/median percentile of its pixels). A raw master's
    sky-glow is far brighter than the faint Ha/OIII signal; without removing it
    a palette remap just yields a flat colour wash. Mono images pass through."""
    if not img.is_color:
        return img.copy()
    data = img.data.astype(np.float32).copy()
    for c in range(3):
        bg = float(np.percentile(data[..., c], percentile))
        data[..., c] = np.clip(data[..., c] - bg, 0.0, 1.0)
    return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))


def _image_like(channels: tuple, like: AstroImage) -> AstroImage:
    rgb = np.clip(np.stack(channels, axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=like.is_linear, metadata=dict(like.metadata))


def hoo(img: AstroImage) -> AstroImage:
    """R=Ha, G=OIII, B=OIII — the honest native duo-band palette."""
    ha, oiii = extract_channels(img)
    return _image_like((ha, oiii, oiii), img)


def pseudo_sho(img: AstroImage) -> AstroImage:
    """Foraxx-inspired gold/teal remap from Ha+OIII only. Not real SHO
    (no SII). Ha -> gold (R+G), OIII -> teal (G+B)."""
    ha, oiii = extract_channels(img)
    r = ha
    g = np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0)
    b = oiii
    return _image_like((r, g, b), img)


_PALETTE_FNS = {"HOO": hoo, "pseudo_SHO": pseudo_sho}


def apply_palette(img: AstroImage, name: str) -> AstroImage:
    if name not in _PALETTE_FNS:
        raise ValueError(f"unknown palette: {name}")
    return _PALETTE_FNS[name](img)


@dataclass
class ChannelCurve:
    black: float = 0.0    # 0..1 input black point
    mid: float = 0.5      # 0..1 slider; 0.5 = neutral gamma
    white: float = 1.0    # 0..1 input white point


@dataclass
class PaletteParams:
    palette: str = "HOO"                         # "HOO" | "pseudo_SHO"
    r: ChannelCurve = field(default_factory=ChannelCurve)
    g: ChannelCurve = field(default_factory=ChannelCurve)
    b: ChannelCurve = field(default_factory=ChannelCurve)
    scnr: bool = True                            # green suppression on the nebula


def apply_channel_curve(channel: np.ndarray, curve: ChannelCurve) -> np.ndarray:
    """Levels on a single 2D channel: remap [black, white] -> [0,1] then midtone
    gamma. Mirrors core/levels.apply_levels. gamma = 10**((mid-0.5)*2)."""
    black = float(curve.black)
    white = max(float(curve.white), black + 1e-4)
    gamma = 10.0 ** ((float(curve.mid) - 0.5) * 2.0)
    x = np.clip((channel - black) / (white - black), 0.0, 1.0)
    return np.power(x, 1.0 / gamma).astype(np.float32)


def neutralize_stars(stars: AstroImage) -> AstroImage:
    """Replace the stars layer's colour with its luminance -> white stars, so
    they don't clash with the false-colour nebula."""
    if not stars.is_color:
        return stars.copy()
    lum = stars.data.mean(axis=2)
    rgb = np.clip(np.stack([lum, lum, lum], axis=2), 0.0, 1.0).astype(np.float32)
    return AstroImage(rgb, is_linear=stars.is_linear, metadata=dict(stars.metadata))


def screen(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Screen blend: 1 - (1-base)*(1-top)."""
    b = np.clip(base, 0.0, 1.0)
    t = np.clip(top, 0.0, 1.0)
    return np.clip(1.0 - (1.0 - b) * (1.0 - t), 0.0, 1.0).astype(np.float32)


def render_nebula(starless: AstroImage, params: PaletteParams) -> AstroImage:
    """Extract Ha/OIII, combine into the chosen palette, sculpt each channel with
    its curve, then optional SCNR green suppression."""
    ha, oiii = extract_channels(starless)
    if params.palette == "pseudo_SHO":
        rgb = [ha, np.clip(0.5 * ha + 0.5 * oiii, 0.0, 1.0), oiii]
    else:  # HOO
        rgb = [ha, oiii, oiii]
    r = apply_channel_curve(rgb[0], params.r)
    g = apply_channel_curve(rgb[1], params.g)
    b = apply_channel_curve(rgb[2], params.b)
    out = np.stack([r, g, b], axis=2)
    if params.scnr:
        avg_rb = (out[..., 0] + out[..., 2]) / 2.0
        out[..., 1] = np.minimum(out[..., 1], avg_rb)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))


def compose(starless: AstroImage, stars: AstroImage, params: PaletteParams) -> AstroImage:
    """render_nebula(starless), then screen neutralize_stars(stars) back on top."""
    nebula = render_nebula(starless, params)
    white = neutralize_stars(stars)
    out = screen(nebula.data, white.data)
    return AstroImage(out, is_linear=starless.is_linear, metadata=dict(starless.metadata))
