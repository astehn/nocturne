from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sep

from .image import AstroImage

_MAX_STARS = 50           # detection cap; the slider picks how many actually draw.
# Fifty, not a hundred: the slider has never offered more than 50, so the other
# half was always detected and thrown away. The cap itself is load-bearing —
# SEP finds 4,887 objects on a 30-minute NGC 281 master, and drawing 2,000
# spikes costs 1.7 s per slider tick on a 39.5 MP frame.
_CANDIDATES = 200         # filtered down to _MAX_STARS, so rejects don't starve it
_MAX_ELONGATION = 2.5     # a/b above this is a trail, a frame edge, or a merged pair
_MAX_SIZE_FACTOR = 3.0    # reject blobs over 3x the median star size for THIS image
_WINPOS_SIG_FACTOR = 0.6  # windowing scale, as a fraction of the object's own radius
_WINPOS_SIG_MIN = 1.0     # ...clamped: a star's window is never this narrow...
_WINPOS_SIG_MAX = 4.0     # ...nor this wide. An unclamped window wanders: on a
# small frame SEP's background box is comparable to the image, which reported a
# sigma-2 star as 14.8 px across, gave a 8.9 px window, and moved the centre 7.4
# px off the star. Real frames give small radii and never reach this, but the
# clamp is what stops a bad background estimate from placing a spike in the dark.
_MAX_LEN_FRAC = 0.08      # longest arm as a fraction of the short edge
_FALLOFF = 2.4            # arm brightness concentration near the core (higher = needlier)
_CORE_SIGMA = 1.4         # arm half-thickness (px) at the core
_TIP_SIGMA = 0.45         # arm half-thickness (px) at the tip (tapers to a point)
_BLOOM_FRAC = 0.09        # core bloom radius as a fraction of arm length
_BLOOM_MIN = 1.5          # minimum bloom radius (px)
_BLOOM_MAX = 5.0          # maximum bloom radius (px) — keep the glow from going milky


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
    h, w = lum.shape
    # Rank by PEAK, not integrated flux. Flux sums the whole blob, so a large
    # diffuse region outranks a genuinely bright star: measured on NGC 281 the
    # top five by flux averaged 1,570 px and the largest was 5,099 — a nebula
    # region, drawn on as though it were a star.
    py = np.clip(objects["ypeak"], 0, h - 1)
    px_ = np.clip(objects["xpeak"], 0, w - 1)
    peak = lum[py, px_]
    cand = objects[np.argsort(peak)[::-1][:_CANDIDATES]]

    # Then keep only what is actually point-like. Sized against THIS image's own
    # stars rather than a fixed pixel count, so it holds at any scale.
    radius = np.sqrt(np.maximum(cand["a"] * cand["b"], 1e-12))
    elongation = cand["a"] / np.maximum(cand["b"], 1e-6)
    keep = (radius <= float(np.median(radius)) * _MAX_SIZE_FACTOR) \
        & (elongation <= _MAX_ELONGATION)
    cand = cand[keep][:_MAX_STARS]
    if len(cand) == 0:
        return []

    # Sub-pixel centre. The isophotal barycentre is the flux-weighted centre of
    # the WHOLE blob, which sits off the visual core when a star has an
    # asymmetric wing or a close neighbour: 11 of 100 were more than 1 px off on
    # NGC 281 and the worst was 3.08 px, against arms 1.4 px thick.
    sub = lum - bkg.back()
    sig = np.clip(np.sqrt(np.maximum(cand["a"] * cand["b"], 1e-12)) * _WINPOS_SIG_FACTOR,
                  _WINPOS_SIG_MIN, _WINPOS_SIG_MAX)
    try:
        wx, wy, wflag = sep.winpos(sub, cand["x"], cand["y"], sig)
    except Exception:
        wx, wy, wflag = cand["x"], cand["y"], np.ones(len(cand), int)

    stars: list[Star] = []
    for n, obj in enumerate(cand):
        flux = float(obj["flux"])
        if flux <= 0:
            continue
        # winpos flags a failure per object; fall back to the barycentre there
        # rather than trusting a number it could not compute.
        good = wflag[n] == 0
        x = float(wx[n]) if good else float(obj["x"])
        y = float(wy[n]) if good else float(obj["y"])
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


def _bbox(cx, cy, tipx, tipy, pad, h, w):
    """Clamped integer bounding box around a segment, padded by `pad` px."""
    x0 = int(max(0, np.floor(min(cx, tipx) - pad)))
    x1 = int(min(w - 1, np.ceil(max(cx, tipx) + pad)))
    y0 = int(max(0, np.floor(min(cy, tipy) - pad)))
    y1 = int(min(h - 1, np.ceil(max(cy, tipy) + pad)))
    return x0, x1, y0, y1


def _splat_arm(layer, cx, cy, ang, arm, wgt, col):
    """Rasterise one tapered, anti-aliased spike arm into `layer` as a distance
    field: brightness falls off sharply toward the tip (needle-like) and the
    cross-section thins from `_CORE_SIGMA` at the core to `_TIP_SIGMA` at the tip.
    Accumulated with `np.maximum` so crossing arms don't over-brighten the core."""
    h, w = layer.shape[:2]
    dx, dy = float(np.cos(ang)), float(np.sin(ang))
    x0, x1, y0, y1 = _bbox(cx, cy, cx + arm * dx, cy + arm * dy,
                           _CORE_SIGMA * 3.0 + 1.0, h, w)
    if x1 < x0 or y1 < y0:
        return
    gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    rx = gx - cx
    ry = gy - cy
    t = rx * dx + ry * dy                          # distance along the arm
    perp = rx * (-dy) + ry * dx                    # perpendicular distance
    frac = np.clip(t / arm, 0.0, 1.0)
    sigma = _TIP_SIGMA + (_CORE_SIGMA - _TIP_SIGMA) * (1.0 - frac)
    inten = wgt * (1.0 - frac) ** _FALLOFF * np.exp(-(perp ** 2) / (2.0 * sigma ** 2))
    inten = np.where((t >= 0.0) & (t <= arm), inten, 0.0).astype(np.float32)
    contrib = inten[:, :, None] * np.asarray(col, np.float32)[None, None, :]
    sub = layer[y0:y1 + 1, x0:x1 + 1]
    np.maximum(sub, contrib, out=sub)


def _splat_bloom(layer, cx, cy, wgt, col, radius):
    """A soft circular core glow so spikes emanate from a bloomed star rather
    than a bare dot. Max-blended into `layer`."""
    h, w = layer.shape[:2]
    x0, x1, y0, y1 = _bbox(cx, cy, cx, cy, radius * 3.0 + 1.0, h, w)
    if x1 < x0 or y1 < y0:
        return
    gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    r2 = (gx - cx) ** 2 + (gy - cy) ** 2
    glow = (wgt * np.exp(-r2 / (2.0 * radius ** 2))).astype(np.float32)
    contrib = glow[:, :, None] * np.asarray(col, np.float32)[None, None, :]
    sub = layer[y0:y1 + 1, x0:x1 + 1]
    np.maximum(sub, contrib, out=sub)


def add_spikes(img: AstroImage, stars: list[Star], length: float, count: int,
               angle: float, intensity: float = 1.0) -> AstroImage:
    """Draw 4-point diffraction spikes on the brightest `count` stars, tinted by
    each star's colour, and screen-blend onto the image. `intensity` (0..1) scales
    the whole spike layer's opacity — 1.0 is full strength, lower makes the spikes
    fainter/more transparent. No-op when length, count, intensity, or stars is 0."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    length = float(np.clip(length, 0.0, 1.0))
    intensity = float(np.clip(intensity, 0.0, 1.0))
    count = int(count)
    mono = data.ndim == 2
    if length <= 0.0 or count <= 0 or intensity <= 0.0 or not stars:
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
        bloom_r = float(np.clip(_BLOOM_FRAC * arm, _BLOOM_MIN, _BLOOM_MAX))
        _splat_bloom(layer, s.x, s.y, wgt, s.color, bloom_r)
        for a in arm_angles:
            _splat_arm(layer, s.x, s.y, a, arm, wgt, s.color)

    screened = 1.0 - (1.0 - rgb) * (1.0 - np.clip(layer * intensity, 0.0, 1.0))
    out = np.clip(screened, 0.0, 1.0)
    if mono:
        out = out.mean(axis=2)
    return AstroImage(out.astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
