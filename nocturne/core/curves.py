from __future__ import annotations

import numpy as np

from .image import AstroImage

_MIN_GAP = 0.02


def _pchip_tangents(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Fritsch–Carlson monotone tangents for cubic Hermite interpolation."""
    n = len(xs)
    h = np.diff(xs)
    delta = np.diff(ys) / h
    m = np.zeros(n)
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    m[0] = delta[0]
    m[-1] = delta[-1]
    return m


def build_lut(points: list[tuple[float, float]], n: int = 1024) -> np.ndarray:
    """A 1-D lookup table over [0,1] from control points, using monotone-cubic
    (Fritsch–Carlson) interpolation so the curve never overshoots or inverts."""
    pts = sorted((float(x), float(y)) for x, y in points)
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)
    grid = np.linspace(0.0, 1.0, n)
    if len(xs) < 2:
        return np.clip(np.full(n, ys[0] if len(ys) else 0.0), 0, 1).astype(np.float32)
    m = _pchip_tangents(xs, ys)
    h = np.diff(xs)
    out = np.empty(n)
    seg = np.clip(np.searchsorted(xs, grid) - 1, 0, len(xs) - 2)
    for s in range(len(xs) - 1):
        mask = seg == s
        if not np.any(mask):
            continue
        t = (grid[mask] - xs[s]) / h[s]
        t2, t3 = t * t, t * t * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        out[mask] = (h00 * ys[s] + h10 * h[s] * m[s]
                     + h01 * ys[s + 1] + h11 * h[s] * m[s + 1])
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def apply_curve(img: AstroImage, points: list[tuple[float, float]]) -> AstroImage:
    """Apply a tone curve (from control `points`) to luminance, preserving hue by
    rescaling RGB with the luminance ratio. Identity points are a no-op."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    lut = build_lut(points)
    mono = data.ndim == 2
    lum = data if mono else data.mean(axis=2)
    idx = lum * (len(lut) - 1)
    lo = np.clip(np.floor(idx).astype(np.int64), 0, len(lut) - 2)
    frac = (idx - lo).astype(np.float32)
    new_lum = lut[lo] * (1.0 - frac) + lut[lo + 1] * frac
    if mono:
        out = new_lum
    else:
        ratio = new_lum / np.maximum(lum, 1e-6)
        out = data * ratio[..., None]
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def gentle_s_points(data: np.ndarray) -> list[tuple[float, float]]:
    """Background-aware 'Add contrast' preset: pin an anchor at the sky level,
    then dip a lower-mid point and lift an upper-mid point for a gentle S that
    raises midtone contrast without lifting the sky."""
    lum = data.mean(axis=2) if data.ndim == 3 else data
    bg = float(np.clip(np.percentile(lum, 10.0), 0.0, 0.5))
    span = 1.0 - bg
    lo_x = bg + span * 0.35
    hi_x = bg + span * 0.75
    d = span * 0.06
    raw = [(0.0, 0.0), (bg, bg),
           (lo_x, lo_x - d), (hi_x, hi_x + d), (1.0, 1.0)]
    # sort, clamp, drop interior points too close together (keeps strictly-increasing x)
    interior = sorted((float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1)))
                      for x, y in raw if 0.0 < x < 1.0)
    out = [(0.0, 0.0)]
    for x, y in interior:
        if x - out[-1][0] >= _MIN_GAP:
            out.append((x, y))
    if len(out) > 1 and (1.0 - out[-1][0]) < _MIN_GAP:
        out.pop()
    out.append((1.0, 1.0))
    return out
