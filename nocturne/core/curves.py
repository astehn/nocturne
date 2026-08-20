from __future__ import annotations

import numpy as np

from .image import AstroImage

_MIN_GAP = 0.02
_DUP_EPS = 1e-9  # x-points closer than this are treated as coincident in build_lut


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
    # Guard against duplicate/near-duplicate x: h = diff(xs) must be strictly
    # positive or the tangent computation divides by zero (-> inf/nan in the
    # LUT). Keep the first point of any near-duplicate cluster. This is a
    # pure robustness guard, not a spacing policy - unlike sanitize_points()
    # it does not force corners or enforce a minimum gap.
    deduped: list[tuple[float, float]] = []
    for x, y in pts:
        if deduped and x - deduped[-1][0] < _DUP_EPS:
            continue
        deduped.append((x, y))
    pts = deduped
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
    # Hold the end values outside the control points instead of letting the
    # polynomial run on. This is what makes a black or white point work: with a
    # low endpoint at (0.25, 0), everything darker must BE black, not a linear
    # continuation into negative territory. Two of the four cases used to be
    # rescued by the clip below — extrapolation left [0,1] and was flattened —
    # so a lifted black point silently crushed the shadows it was lifting.
    out[grid < xs[0]] = ys[0]
    out[grid > xs[-1]] = ys[-1]
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


def sanitize_points(pts, min_gap: float = _MIN_GAP) -> list[tuple[float, float]]:
    """Sort control points, clamp to [0,1], and enforce a minimum x-gap.

    The endpoints are whatever the user put there. They used to be forced to
    (0,0) and (1,1), which made a black or white point — dragging the low
    endpoint right, or the high one left — impossible to express: the drag was
    discarded the instant it was committed. `build_lut` holds the end values
    outside the point range, so a moved endpoint clips or rolls off exactly as
    it should.

    What still has to hold is what build_lut depends on: sorted, inside [0,1],
    and strictly increasing in x.
    """
    ordered = sorted((float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1)))
                     for x, y in pts)
    if not ordered:
        return [(0.0, 0.0), (1.0, 1.0)]
    out = [ordered[0]]
    for x, y in ordered[1:]:
        if x - out[-1][0] >= min_gap:
            out.append((x, y))
    if len(out) < 2:                       # a curve needs two points to exist
        x0, y0 = out[0]
        out = [(0.0, y0), (1.0, y0)] if x0 in (0.0, 1.0) else [(0.0, 0.0), (1.0, 1.0)]
    return out


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
    return sanitize_points(raw)


def _sky_level(data: np.ndarray) -> tuple[float, float]:
    """(sky, span) for the image — the anchor every preset works relative to.

    Measured, never assumed. Colour Balance's band presets originally used
    absolute positions, and on M 31 — whose stretched sky sits at 0.256 — they
    selected 87% of the frame, the inverse of the intent. A curve preset with
    fixed point positions fails the same way: 'lift the shadows' means something
    different on a Bortle 3 sky and a light-polluted one.
    """
    lum = data.mean(axis=2) if data.ndim == 3 else data
    sky = float(np.clip(np.percentile(lum, 10.0), 0.0, 0.5))
    return sky, 1.0 - sky


def strong_s_points(data: np.ndarray) -> list[tuple[float, float]]:
    """'Add contrast', pushed harder — for a flat image the gentle one barely
    moves. Same shape, twice the deflection (0.12 of the span against 0.06)."""
    sky, span = _sky_level(data)
    d = span * 0.12
    raw = [(0.0, 0.0), (sky, sky),
           (sky + span * 0.35, sky + span * 0.35 - d),
           (sky + span * 0.75, sky + span * 0.75 + d),
           (1.0, 1.0)]
    return sanitize_points(raw)


def lift_faint_points(data: np.ndarray) -> list[tuple[float, float]]:
    """Bring up outer nebulosity and dust WITHOUT greying the background.

    Pinning the sky is the whole point, and what separates this from simply
    brightening: the lift starts just above the sky and fades out by the
    midtones, so the background keeps its level while the faint signal sitting
    on top of it comes up.
    """
    sky, span = _sky_level(data)
    x1 = sky + span * 0.15
    x2 = sky + span * 0.45
    raw = [(0.0, 0.0), (sky, sky),
           (x1, x1 + span * 0.07),
           (x2, x2 + span * 0.04),
           (1.0, 1.0)]
    return sanitize_points(raw)


def deepen_sky_points(data: np.ndarray) -> list[tuple[float, float]]:
    """Darken the background for a cleaner field, without crushing the faint
    signal just above it — which is what a plain black-point slide would do.

    The sky comes down; the point above it is held UP, so the gap between
    background and faint detail widens instead of collapsing.
    """
    sky, span = _sky_level(data)
    drop = min(sky * 0.5, span * 0.05)
    raw = [(0.0, 0.0),
           (sky, max(0.0, sky - drop)),
           (sky + span * 0.30, sky + span * 0.30 + span * 0.02),
           (1.0, 1.0)]
    return sanitize_points(raw)


def tame_highlights_points(data: np.ndarray) -> list[tuple[float, float]]:
    """Roll the top end off so blown star and galaxy cores recover some shape.

    Finds where THIS image's highlights actually are, not a fixed fraction of
    the span. That distinction was found on real data: with the roll-off pinned
    at 80% of the span, the M 31 mosaic's bright end (0.773) fell BELOW the
    start of the roll-off, so the preset never reached the highlights it exists
    to tame — and the monotone spline bulged slightly above the identity line on
    the way there, brightening them by +0.0098 instead.

    The knee sits just below the bright end, and the curve is pinned on identity
    up to it, so nothing below the highlights moves and nothing is ever lifted.

    Deliberately gentle: Recover Core does this properly on LINEAR data earlier
    in the pipeline, and this is a finishing touch rather than a substitute.
    """
    lum = data.mean(axis=2) if data.ndim == 3 else data
    sky, span = _sky_level(data)
    # where the picture's highlights actually live
    top = float(np.clip(np.percentile(lum, 99.0), sky + span * 0.25, 1.0))
    knee = max(sky + span * 0.10, top - span * 0.25)
    drop = (1.0 - knee) * 0.22
    # Two extra anchors on the identity line between the sky and the knee.
    # Monotone-cubic interpolation guarantees the curve never INVERTS, but not
    # that it stays below its own chord: the descending segment after the knee
    # pulls the tangent there below 1.0, which bows the preceding segment
    # upward. Measured worst case across sky and highlight levels: 3.44 8-bit
    # levels of lift with no anchors, 0.40 with these two — below one
    # quantisation step, so it cannot reach any output.
    a1 = sky + (knee - sky) * 0.50
    a2 = sky + (knee - sky) * 0.85
    raw = [(0.0, 0.0), (sky, sky), (a1, a1), (a2, a2),
           (knee, knee), (1.0, max(knee, 1.0 - drop))]
    return sanitize_points(raw)
