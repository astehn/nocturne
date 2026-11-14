"""Painted background: fit a smooth sky surface to the sky the user painted.

The October spike (docs/BUILT_IN_BGE_SPIKE_2026-10-21.md) showed fitting a
surface is solved and choosing the sky is the whole problem — automatic
rejection read moon glow as nebula. So the user's strokes decide where they
paint: a box touched by Nebula paint is never sky, a box mostly painted Sky
always is, and only unpainted boxes go through the spike's iterative
selection (``iter.py`` ``model_iter``, its best on every gradient shape).

Timing (2026-11-14, this Mac, synthetic 3840x2160x3 float32): apply_painted
2.4 s with or without strokes (box sampling 0.8 s, RBF on a 480x270 grid
1.0 s, cubic upsample 0.7 s); auto_labels 0.8 s.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import minimum_filter, uniform_filter

from nocturne.core.image import AstroImage

UNPAINTED, SKY, NEBULA = 0, 1, 2

# Box grid: the spike's best runs used 48 boxes on the long edge (iter.py);
# the floor of 8 on the short side keeps a 300x200 crop fittable.
_N_LONG = 48
_MIN_SHORT = 8
# Star rejection inside a box: stars only push luminance UP, so the brightest
# 10% go and the rest give the median.
_STAR_CLIP = 0.90
# A box with more than 2% empty (all-zero) pixels sits on a stacking or
# mosaic edge: its median is dragged toward black, so it is never sky.
_MAX_ZERO = 0.02
_MIN_SKY_PAINT = 0.5
# Spike iter.py selection, unchanged: recovered 96-99% on linear/corner and
# was the best automatic method on moon/patchy.
_K_HI, _K_LO, _PASSES, _SMOOTH = 1.5, 5.0, 6, 1.0
# The outer box ring and the edge strips: a stack's coverage border is a
# narrow band of brighter sky (his M 33 master: the per-column sky median climbs
# to +15 sigma in the outer ~100 px), and _K_HI rejected the whole right-hand box
# column there, so the surface stayed flat and left the band in. Measured on that
# master (3840 tall x 2160 wide, median residual in sigma, outer 40 px / 40-200 px in):
# right edge 16.6 / 3.1 before, 11.7 / 0.1 with the strips and this clip; left
# 6.9 -> 3.3, top 3.9 -> 2.6, bottom 1.4 -> 0.8. The outer 40 px keep part of
# the band: the stiff surface (_SMOOTH 1.0) cannot bend within half a box. Not
# pinned as sky: a nebula touching the edge (NGC 7000) must stay rejectable.
_K_HI_EDGE = 5.0
_MIN_BOXES = 12
_FIT_EDGE = 512

_TOO_LITTLE_SKY = ("Too little sky left to fit the background — "
                   "paint some sky, or less nebula.")


@dataclass
class BoxSelection:
    pts: np.ndarray        # (n, 2) box centres, (y/h, x/w)
    vals: np.ndarray       # (n, c) star-rejected box medians
    keep: np.ndarray       # (n,) bool — the boxes the fit uses
    forced: np.ndarray     # (n,) int8 — +1 painted sky, -1 nebula/empty, 0 automatic
    grid: tuple[int, int]  # (ny, nx)
    box: int               # box edge, px
    origin: tuple[int, int]  # (oy, ox) of the first box


# ---------------------------------------------------------------- strokes
def rasterize_strokes(strokes: list[dict], shape: tuple[int, int]) -> np.ndarray:
    """Strokes are capsules (centre line + radius) painted in list order."""
    h, w = int(shape[0]), int(shape[1])
    lab = np.zeros((h, w), np.uint8)
    value = {"sky": SKY, "nebula": NEBULA, "erase": UNPAINTED}
    for s in strokes or []:
        pts = np.asarray(s.get("points") or [], np.float64).reshape(-1, 2)
        if not len(pts):
            continue
        r = float(s.get("radius", 0.0))
        v = value[s["kind"]]
        segs = zip(pts, pts[1:]) if len(pts) > 1 else [(pts[0], pts[0])]
        for a, b in segs:
            x0 = max(0, int(np.floor(min(a[0], b[0]) - r)))
            x1 = min(w, int(np.ceil(max(a[0], b[0]) + r)) + 1)
            y0 = max(0, int(np.floor(min(a[1], b[1]) - r)))
            y1 = min(h, int(np.ceil(max(a[1], b[1]) + r)) + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
            d = b - a
            dd = float(d @ d)
            t = 0.0 if dd == 0 else np.clip(((xx - a[0]) * d[0] + (yy - a[1]) * d[1]) / dd, 0, 1)
            inside = (xx - a[0] - t * d[0]) ** 2 + (yy - a[1] - t * d[1]) ** 2 <= r * r
            lab[y0:y1, x0:x1][inside] = v
    return lab


# ---------------------------------------------------------------- boxes
def _as3(data: np.ndarray) -> np.ndarray:
    data = np.asarray(data, np.float32)
    return data[..., None] if data.ndim == 2 else data


def _grid(h: int, w: int) -> tuple[int, int, int, int, int]:
    bs = max(1, min(max(h, w) // _N_LONG, min(h, w) // _MIN_SHORT))
    ny, nx = h // bs, w // bs
    return bs, ny, nx, (h - ny * bs) // 2, (w - nx * bs) // 2


def _boxes(a: np.ndarray, bs, ny, nx, oy, ox) -> np.ndarray:
    """(ny, nx, bs*bs, ...) view of the gridded area."""
    sub = a[oy:oy + ny * bs, ox:ox + nx * bs]
    tail = sub.shape[2:]
    return (sub.reshape((ny, bs, nx, bs) + tail).swapaxes(1, 2)
            .reshape((ny, nx, bs * bs) + tail))


def _medians(boxes: np.ndarray) -> np.ndarray:
    """Star-rejected median of each (n, m, c) sample box."""
    m = boxes.shape[1]
    lum = boxes.mean(axis=2)
    k = max(1, int(np.ceil(_STAR_CLIP * m)))
    darkest = np.argsort(lum, axis=1, kind="stable")[:, :k]
    return np.median(np.take_along_axis(boxes, darkest[..., None], axis=1),
                     axis=1).astype(np.float64)


def _force(boxes, lb) -> np.ndarray:
    """Painted label and zero-coverage forcing, shared by boxes and strips."""
    forced = np.zeros(len(boxes), np.int8)
    if lb is not None:
        forced[(lb == SKY).mean(axis=1) >= _MIN_SKY_PAINT] = 1
        forced[(lb == NEBULA).any(axis=1)] = -1
    forced[(boxes == 0).all(axis=2).mean(axis=1) > _MAX_ZERO] = -1
    return forced


def _strips(d, labels, bs, ny, nx, oy, ox):
    """Half-depth boxes along the four frame edges: bs/2 deep, centred bs/4 in,
    one per box-grid column/row. The outer box ring is centred bs/2 in from the
    grid (more on an uneven crop), so a stack's narrow bright coverage border
    lay outside every sample and the stiff surface stayed flat over it.
    Returns (pts, boxes, label boxes or None)."""
    h, w, c = d.shape
    q = bs // 2
    if q < 2:
        return None
    pts, boxes, labs = [], [], []
    cols = [slice(ox + i * bs, ox + (i + 1) * bs) for i in range(nx)]
    rows = [slice(oy + j * bs, oy + (j + 1) * bs) for j in range(ny)]
    for i, cs in enumerate(cols):
        for rs, yc in ((slice(0, q), q / 2), (slice(h - q, h), h - q / 2)):
            pts.append((yc / h, (ox + (i + 0.5) * bs) / w))
            boxes.append(d[rs, cs].reshape(-1, c))
            labs.append(None if labels is None else labels[rs, cs].ravel())
    for j, rs in enumerate(rows):
        for cs, xc in ((slice(0, q), q / 2), (slice(w - q, w), w - q / 2)):
            pts.append(((oy + (j + 0.5) * bs) / h, xc / w))
            boxes.append(d[rs, cs].reshape(-1, c))
            labs.append(None if labels is None else labels[rs, cs].ravel())
    lb = None if labels is None else np.stack(labs)
    return np.array(pts), np.stack(boxes), lb


def select_sky(data: np.ndarray, labels: np.ndarray | None) -> BoxSelection:
    """The first ny*nx entries are the box grid (row-major); the edge strips
    follow."""
    d = _as3(data)
    h, w, c = d.shape
    bs, ny, nx, oy, ox = _grid(h, w)
    boxes = _boxes(d, bs, ny, nx, oy, ox).reshape(ny * nx, bs * bs, c)
    vals = _medians(boxes)
    lb = None
    if labels is not None:
        labels = np.asarray(labels)
        lb = _boxes(labels, bs, ny, nx, oy, ox).reshape(ny * nx, -1)
    forced = _force(boxes, lb)

    jj, ii = np.divmod(np.arange(ny * nx), nx)
    pts = np.stack([(oy + (jj + 0.5) * bs) / h, (ox + (ii + 0.5) * bs) / w], axis=1)
    strips = _strips(d, labels, bs, ny, nx, oy, ox)
    if strips is not None:
        s_pts, s_boxes, s_lb = strips
        pts = np.vstack([pts, s_pts])
        vals = np.vstack([vals, _medians(s_boxes)])
        forced = np.concatenate([forced, _force(s_boxes, s_lb)])
    keep = _iterate(pts, vals.mean(axis=1), forced, ny, nx)
    return BoxSelection(pts, vals, keep, forced, (ny, nx), bs, (oy, ox))


def _iterate(pts, lum, forced, ny, nx) -> np.ndarray:
    """Spike ``model_iter`` selection with painted boxes pinned every pass.

    ``pts``/``lum``/``forced`` hold the ny*nx grid first, then any edge
    strips. The outer box ring and the strips get the looser ``_K_HI_EDGE``
    upper clip."""
    try:
        return _iterate_fit(pts, lum, forced, ny, nx)
    except np.linalg.LinAlgError:
        # Nebula everywhere but a row or two of boxes: the surviving centres
        # are collinear and the plane term of the fit is singular.
        raise ValueError(_TOO_LITTLE_SKY) from None


def _iterate_fit(pts, lum, forced, ny, nx) -> np.ndarray:
    n = ny * nx
    cand = forced != -1
    if cand.sum() < _MIN_BOXES:
        raise ValueError(_TOO_LITTLE_SKY)
    ring = np.zeros((ny, nx), bool)
    ring[0] = ring[-1] = True
    ring[:, 0] = ring[:, -1] = True
    edge = np.concatenate([ring.ravel(), np.ones(len(lum) - n, bool)])
    L = lum[:n].reshape(ny, nx)
    c2 = cand[:n].reshape(ny, nx)
    if not c2.any():
        raise ValueError(_TOO_LITTLE_SKY)
    # Noise from neighbouring box pairs that are both candidates: an empty
    # border next to sky would otherwise read as a huge "noise".
    pair = c2[:, 1:] & c2[:, :-1]
    diffs = np.abs(np.diff(L, axis=1))[pair] if pair.any() else np.abs(np.diff(L, axis=1)).ravel()
    noise = float(np.median(diffs)) * 1.4826 + 1e-12
    # Excluded boxes must not set the local floor (a black border would).
    Lf = np.where(c2, L, L[c2].max())
    floor = uniform_filter(minimum_filter(Lf, 5, mode="nearest"), 5, mode="nearest").ravel()
    # Strips start as candidates: the floor is a 5x5 minimum over the grid, so
    # it has no sample of a strip's own band and cannot judge it (floor-testing
    # them left M 33's right edge at 13.2 sigma, against 11.7 this way). The
    # passes below still reject one that sits above the fit.
    floor = np.concatenate([floor, np.full(len(lum) - n, np.inf)])
    keep = lum < floor + np.where(edge, _K_HI_EDGE, 2.0) * noise
    keep = _pin(keep, forced)
    if keep.sum() < _MIN_BOXES:
        keep = cand.copy()
    k_hi = np.where(edge, _K_HI_EDGE, _K_HI)
    sc = lum[keep].std() + 1e-12
    for _ in range(_PASSES):
        fit = RBFInterpolator(pts[keep], lum[keep] / sc, kernel="thin_plate_spline",
                              smoothing=_SMOOTH, degree=1)(pts) * sc
        r = lum - fit
        s = max(float(np.median(np.abs(r[keep]))) * 1.4826, noise)
        new = _pin((r < k_hi * s) & (r > -_K_LO * s), forced)
        if new.sum() < _MIN_BOXES or (new == keep).all():
            break
        keep = new
    if keep.sum() < _MIN_BOXES:
        raise ValueError(_TOO_LITTLE_SKY)
    return keep


def _pin(keep, forced):
    keep = keep.copy()
    keep[forced == 1] = True
    keep[forced == -1] = False
    return keep


def auto_labels(data: np.ndarray, labels: np.ndarray | None) -> np.ndarray:
    """What the fit will treat as sky, at full resolution, for the editor."""
    d = _as3(data)
    h, w = d.shape[:2]
    sel = select_sky(d, labels)
    ny, nx = sel.grid
    bs = sel.box
    oy, ox = sel.origin
    box_lab = np.where(sel.keep[:ny * nx], SKY, NEBULA).astype(np.uint8).reshape(ny, nx)
    full = np.repeat(np.repeat(box_lab, bs, axis=0), bs, axis=1)
    full = np.pad(full, ((oy, h - oy - ny * bs), (ox, w - ox - nx * bs)), mode="edge")
    if labels is not None:
        labels = np.asarray(labels)
        full = np.where(labels != UNPAINTED, labels, full).astype(np.uint8)
    return full


# ---------------------------------------------------------------- fit
def _model(d: np.ndarray, sel: BoxSelection) -> np.ndarray:
    from skimage.transform import resize

    h, w, c = d.shape
    f = int(np.ceil(max(h, w) / _FIT_EDGE))
    sh, sw = max(1, int(np.ceil(h / f))), max(1, int(np.ceil(w / f)))
    gy, gx = np.mgrid[0:sh, 0:sw]
    grid = np.stack([(gy.ravel() + .5) / sh, (gx.ravel() + .5) / sw], axis=1)
    vals = sel.vals[sel.keep]
    scale = vals.std() + 1e-12
    try:
        rbf = RBFInterpolator(sel.pts[sel.keep], vals / scale, kernel="thin_plate_spline",
                              smoothing=_SMOOTH, degree=1)
        small = (rbf(grid) * scale).reshape(sh, sw, c)
    except np.linalg.LinAlgError:
        raise ValueError(_TOO_LITTLE_SKY) from None
    if (sh, sw) == (h, w):
        return small.astype(np.float32)
    # Per channel: a 3-D resize also runs the cubic spline along the channel
    # axis and took 5.8 s of a 7.6 s 8 MP fit; 2-D per channel 0.7 s, equal
    # to 1e-15 on a smooth model.
    return np.stack([resize(small[..., i], (h, w), order=3, preserve_range=True,
                            anti_aliasing=False) for i in range(c)],
                    axis=2).astype(np.float32)


def background_model(data: np.ndarray, labels: np.ndarray | None) -> np.ndarray:
    d = _as3(data)
    model = _model(d, select_sky(d, labels))
    return model[..., 0] if np.ndim(data) == 2 else model


def apply_painted(img: AstroImage, strokes: list[dict] | None,
                  amount: float) -> tuple[AstroImage, np.ndarray]:
    """Subtract ``amount`` of the model, re-levelled to the sky's median so
    the sky keeps its level (the GraXpert route's pedestal behaviour)."""
    d = _as3(img.data)
    h, w, _ = d.shape
    labels = rasterize_strokes(strokes or [], (h, w)) if strokes else None
    sel = select_sky(d, labels)
    model = _model(d, sel)
    ys = np.minimum((sel.pts[sel.keep, 0] * h).astype(int), h - 1)
    xs = np.minimum((sel.pts[sel.keep, 1] * w).astype(int), w - 1)
    pedestal = np.median(model[ys, xs], axis=0).astype(np.float32)
    sub = (np.float32(amount) * (model - pedestal)).astype(np.float32)
    out = np.maximum(d - sub, 0.0).astype(np.float32)
    out[(d == 0).all(axis=2)] = 0.0
    if img.data.ndim == 2:
        out, sub = out[..., 0], sub[..., 0]
    return AstroImage(out, img.is_linear, dict(img.metadata)), sub
