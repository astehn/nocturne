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


# --- channel and hue-range curves --------------------------------------------
#
# AstroWizard's Curves dialog, which is what Andreas asked for on 2026-09-05,
# has two selectors rather than one: a CHANNEL (RGB, R, G, B, or S for
# saturation) and a TARGET hue range. "S + Reds" is a saturation curve applied
# only to the reds. Five channels times seven targets is a matrix of curves
# reached through two small controls instead of a wall of sliders.
#
# See docs/HSL_DESIGN_QUESTION.md for why this shape, and why "hue per RGB
# channel" — the literal request — is not a definable thing.

CURVE_CHANNELS = ("rgb", "r", "g", "b", "s")

# Six ranges, not Lightroom's eight: orange/aqua/purple carve up hues this data
# barely contains, and every extra target is another hidden state the user has
# to remember they touched. These six are what actually appears in OSC astro —
# Ha, the warm star population, the green nobody wants, OIII, reflection
# nebulosity, and the magenta halo cast.
CURVE_RANGES = ("all", "reds", "yellows", "greens", "cyans", "blues", "magentas")

# Hue angle of each range's centre, in turns. Evenly spaced by construction:
# with a triangular falloff one width wide, the six weights sum to exactly 1 at
# every hue, so a curve applied identically to all six equals the same curve
# applied to "all". A partition of unity is what stops the boundaries showing.
_RANGE_CENTRE = {"reds": 0.0, "yellows": 1 / 6, "greens": 2 / 6,
                 "cyans": 3 / 6, "blues": 4 / 6, "magentas": 5 / 6}
_RANGE_WIDTH = 1 / 6


def _hue_sat(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Hue in turns [0,1) and HSV saturation [0,1], per pixel.

    Saturation matters as much as hue here: a grey pixel has no meaningful hue,
    and without weighting by saturation a hue-targeted curve would grab the
    entire background — which on an astro frame is most of the picture, and
    would make "Reds" behave like "All colours" on anything but a bright nebula.
    """
    cmax = data.max(axis=2)
    cmin = data.min(axis=2)
    chroma = cmax - cmin
    safe = np.maximum(chroma, 1e-6)
    r, g, b = data[..., 0], data[..., 1], data[..., 2]
    hue = np.where(cmax == r, ((g - b) / safe) % 6.0,
                   np.where(cmax == g, (b - r) / safe + 2.0,
                            (r - g) / safe + 4.0)) / 6.0
    hue = np.where(chroma <= 1e-6, 0.0, hue % 1.0)
    return hue.astype(np.float32), (chroma / np.maximum(cmax, 1e-6)).astype(np.float32)


def range_weight(data: np.ndarray, name: str) -> np.ndarray | None:
    """Per-pixel 0..1 weight for one hue range, or None for "all" (meaning no
    mask at all, which lets the caller skip the multiply entirely)."""
    if name == "all":
        return None
    centre = _RANGE_CENTRE[name]
    hue, sat = _hue_sat(data)
    d = np.abs(hue - centre)
    d = np.minimum(d, 1.0 - d)                       # wrap around the wheel
    return (np.clip(1.0 - d / _RANGE_WIDTH, 0.0, 1.0) * sat).astype(np.float32)


def _through_lut(values: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """`values` in [0,1] mapped through `lut`, linearly interpolated."""
    idx = np.clip(values, 0.0, 1.0) * (len(lut) - 1)
    lo = np.clip(np.floor(idx).astype(np.int64), 0, len(lut) - 2)
    frac = (idx - lo).astype(np.float32)
    return lut[lo] * (1.0 - frac) + lut[lo + 1] * frac


def _is_identity(points) -> bool:
    """A curve that does nothing. Worth detecting rather than applying: the
    matrix has 35 slots and all but one or two are normally untouched, so this
    is what keeps the cost proportional to what the user actually edited."""
    return all(abs(float(y) - float(x)) < 1e-6 for x, y in points)


def curve_key(channel: str, target: str) -> str:
    """One slot of the matrix, as a string — because this is stored in recipes
    and project bundles, which are JSON, where a tuple key cannot survive."""
    return f"{channel}/{target}"


def normalize_curves(option) -> dict:
    """Accept every shape the Curves option has ever had, return the matrix.

    A BARE LIST OF POINTS is how every project and recipe written before
    2026-09-05 stored this step, and those must keep working: a saved recipe
    that silently stopped applying its curve would be the worst kind of
    regression, because the batch still succeeds and only the pictures are
    wrong. A bare list means what it always meant — the RGB curve over all
    colours.
    """
    if option is None or option == "":
        return {}
    if isinstance(option, dict):
        return {k: [(float(x), float(y)) for x, y in v]
                for k, v in option.items() if v and not _is_identity(v)}
    pts = [(float(x), float(y)) for x, y in option]
    return {} if _is_identity(pts) else {curve_key("rgb", "all"): pts}


def active_curves(option) -> list[str]:
    """Labels of the slots that actually do something, for the dialog's
    "Active curves:" line. A matrix this size hides its own state — without
    this the user cannot tell that a curve they set on Reds twenty minutes ago
    is still shaping the picture."""
    labels = {"rgb": "RGB", "r": "R", "g": "G", "b": "B", "s": "S"}
    out = []
    for key in sorted(normalize_curves(option),
                      key=lambda k: CURVE_CHANNELS.index(k.split("/")[0])):
        channel, target = key.split("/")
        label = labels[channel]
        out.append(label if target == "all" else f"{label}·{target.capitalize()}")
    return out


def _curved(data: np.ndarray, channel: str, lut: np.ndarray) -> np.ndarray:
    """`data` with one channel's curve applied, unmasked."""
    if channel == "rgb":
        # Hue-preserving, exactly as apply_curve has always been: the whole
        # pixel is rescaled by the luminance ratio.
        lum = data.mean(axis=2)
        ratio = _through_lut(lum, lut) / np.maximum(lum, 1e-6)
        return data * ratio[..., None]
    if channel in ("r", "g", "b"):
        # Deliberately NOT hue-preserving — moving one channel alone is how you
        # shift a colour, and it is the reason this channel exists.
        out = data.copy()
        i = "rgb".index(channel)
        out[..., i] = _through_lut(data[..., i], lut)
        return out
    # saturation: chroma scaled about luminance, the same definition
    # core.saturation.saturate uses, so the two tools cannot disagree about
    # what "more saturated" means.
    lum = data.mean(axis=2, keepdims=True)
    cmax, cmin = data.max(axis=2), data.min(axis=2)
    sat = (cmax - cmin) / np.maximum(cmax, 1e-6)
    gain = _through_lut(sat, lut) / np.maximum(sat, 1e-6)
    return lum + (data - lum) * gain[..., None]


def apply_curves(img: AstroImage, option) -> AstroImage:
    """Every curve in the matrix, in a FIXED order: RGB, then R/G/B, then S.

    Fixed because these do not commute — a red curve followed by a saturation
    curve is not the same picture as the reverse — and a dialog that applied
    them in whatever order the user happened to edit would give two different
    results from identical settings, and a recipe would not reproduce.
    """
    curves = normalize_curves(option)
    if not curves:
        return img.copy()
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    mono = data.ndim == 2
    if mono:
        # Only the RGB (tone) curve means anything without colour. Silently
        # ignoring the rest beats raising: a mono frame can legitimately reach a
        # recipe written on a colour one.
        pts = curves.get(curve_key("rgb", "all"))
        return apply_curve(img, pts) if pts else img.copy()

    for key in sorted(curves, key=lambda k: CURVE_CHANNELS.index(k.split("/")[0])):
        channel, target = key.split("/")
        lut = build_lut(curves[key])
        curved = _curved(data, channel, lut)
        w = range_weight(data, target)
        data = curved if w is None else data + (curved - data) * w[..., None]
        data = np.clip(data, 0.0, 1.0)
    return AstroImage(data.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))
