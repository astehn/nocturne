from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sep

from .image import AstroImage

_MAX_STARS = 100          # detection cap; the slider picks how many actually draw
_MAX_LEN_FRAC = 0.08      # longest arm as a fraction of the short edge
_THICKNESS = 1.0          # gaussian sigma (px) across each arm


@dataclass
class Star:
    x: float          # column centroid
    y: float          # row centroid
    flux: float
    color: tuple


def detect_stars(data: np.ndarray) -> list[Star]:
    """Detect stars via SEP on the display-space luminance; return them
    brightest-first with a sampled RGB colour. `data` is HxWx3 or HxW in [0,1]."""
    mono = data.ndim == 2
    lum = np.ascontiguousarray(data if mono else data.mean(axis=2), dtype=np.float32)
    try:
        bkg = sep.Background(lum)
        objects = sep.extract(lum - bkg.back(), 5.0, err=bkg.globalrms)
    except Exception:
        return []
    if len(objects) == 0:
        return []
    order = np.argsort(objects["flux"])[::-1][:_MAX_STARS]
    h, w = lum.shape
    stars: list[Star] = []
    for i in order:
        flux = float(objects["flux"][i])
        if flux <= 0:
            continue
        x = float(objects["x"][i])
        y = float(objects["y"][i])
        xi = int(np.clip(round(x), 0, w - 1))
        yi = int(np.clip(round(y), 0, h - 1))
        if mono:
            color = (1.0, 1.0, 1.0)
        else:
            px = data[yi, xi].astype(np.float32)
            m = float(px.max())
            color = tuple((px / m).tolist()) if m > 1e-6 else (1.0, 1.0, 1.0)
        stars.append(Star(x, y, flux, color))
    return stars


def _splat_line(layer, xs, ys, fall, col):
    """Accumulate a gaussian-thickness line into `layer` (HxWx3): each sample
    point (xs[i], ys[i]) with intensity fall[i], tinted by `col`."""
    h, w = layer.shape[:2]
    xi = np.round(xs).astype(np.int64)
    yi = np.round(ys).astype(np.int64)
    for dxp in (-1, 0, 1):
        for dyp in (-1, 0, 1):
            wgt = float(np.exp(-(dxp * dxp + dyp * dyp) / (2.0 * _THICKNESS ** 2)))
            xx = xi + dxp
            yy = yi + dyp
            m = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
            if not np.any(m):
                continue
            contrib = (fall[m] * wgt)[:, None] * np.asarray(col, np.float32)[None, :]
            np.add.at(layer, (yy[m], xx[m]), contrib)


def add_spikes(img: AstroImage, stars: list[Star], length: float, count: int,
               angle: float) -> AstroImage:
    """Draw 4-point diffraction spikes on the brightest `count` stars, tinted by
    each star's colour, and screen-blend onto the image. No-op when length or
    count is 0 or there are no stars."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    length = float(np.clip(length, 0.0, 1.0))
    count = int(count)
    mono = data.ndim == 2
    if length <= 0.0 or count <= 0 or not stars:
        return AstroImage(data, is_linear=img.is_linear, metadata=dict(img.metadata))

    h, w = data.shape[:2] if not mono else data.shape
    rgb = np.repeat(data[:, :, None], 3, axis=2) if mono else data
    layer = np.zeros((h, w, 3), np.float32)

    chosen = stars[:count]
    fmax = max(s.flux for s in chosen) or 1.0
    max_len = _MAX_LEN_FRAC * min(h, w)
    arm_angles = [np.deg2rad(angle) + k * np.pi / 2 for k in range(4)]

    for s in chosen:
        wgt = float(np.clip(s.flux / fmax, 0.0, 1.0))
        arm = max_len * (0.4 + 0.6 * wgt) * length
        if arm < 1.0:
            continue
        n = int(arm * 2) + 2
        ts = np.linspace(0.0, arm, n)
        fall = wgt * (1.0 - ts / arm)
        for a in arm_angles:
            _splat_line(layer, s.x + ts * np.cos(a), s.y + ts * np.sin(a), fall, s.color)

    screened = 1.0 - (1.0 - rgb) * (1.0 - np.clip(layer, 0.0, 1.0))
    out = np.clip(screened, 0.0, 1.0)
    if mono:
        out = out.mean(axis=2)
    return AstroImage(out.astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
