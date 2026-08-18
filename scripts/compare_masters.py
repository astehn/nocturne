"""Compare two masters' star sharpness with a depth-independent metric.

    compare_masters.py NOCTURNE.fits SIRIL.fits

WHY NOT sep's FWHM: sep reports isophotal moments, and an isophote grows with
signal-to-noise. A deeper or better-stretched image measures every star broader
for reasons that have nothing to do with sharpness. That invalidated an earlier
claim in this project ("stacking degrades stars 11%") and is why the M 31
Nocturne-vs-Siril comparison could never be settled.

WHY NOT A PER-STAR GAUSSIAN FIT (the previous version of this script): on the
M 45 masters the stars have sigma ~1.1 px, i.e. FWHM ~2.6 px, which is badly
undersampled. A log-linear fit to pixel-CENTRE samples of such a profile is
biased and noisy, because the data are pixel-INTEGRATED. Measured: only 2.4% of
isolated stars yielded a usable fit (73 of 3064), and a known-blur validation
swung between -2.6% and +5.1%. Cleaning the fit up — local background,
core-only mask, intensity weighting — recovered exactly ONE more star. The fit
was never the problem.

WHAT THIS DOES INSTEAD — a stacked empirical PSF:

1. Detect stars in both images, and solve the geometry between them
   (translation by voting, plus a row-flip check: Nocturne and Siril disagree
   about FITS row order, and a reflection defeats both voting and astroalign).
2. Take star positions from image A ONLY, and sample image B at those same
   positions mapped through the transform.
3. Stack a 4x oversampled PSF for each image. Stars land at random sub-pixel
   phases, so combining ~2000 of them reconstructs the continuous PSF — the
   dithering principle. This also uses every matched star instead of the few
   percent that survive an individual fit, so the noise floor drops as sqrt(N).
4. Measure the half-light radius of each stacked PSF inside a FIXED aperture,
   about the PSF's own centroid.

THE COMMON POSITION SOURCE IN STEP 2 IS THE WHOLE TRICK. Measuring each image
at its own detected positions fails, because centroid error grows with noise
and a stacked PSF is broadened by the centroid-error distribution — so the
NOISIER image reads as SOFTER. Measured on real data: adding noise while
changing nothing about sharpness produced +5.0%, +7.5% and +17.3% of spurious
"softening", as large as any difference worth finding. Sharing one position
source makes that error common-mode, and it cancels in the ratio.

A FIXED aperture matters for the same reason an isophote was rejected: an
isophote moves with depth, a fixed aperture does not.

VALIDATION (M 45 Siril master, 1978 stars):
    identical copy              -0.000%   (exact)
    +2x noise, same positions    -0.55%
    sub-pixel offsets to 0.6 px  +0.48%
    0.1 px Fourier-domain blur   +0.48%
    0.5 px blur                 +11.45%
So the floor is ~0.5% and anything at or above ~1% is real. Note that blur must
be applied in the FOURIER domain to validate this: scipy.ndimage.gaussian_filter
truncates its kernel to radius 1 below sigma 0.3, so small-sigma test blurs are
near no-ops and fake a dead zone in the metric.
"""
import sys

sys.path.insert(0, "/Volumes/Work/Code/Editor")

import numpy as np  # noqa: E402

_MAX_PEAK = 0.95        # a clipped core has no profile to measure
# A star must rise this far above the background NOISE to contribute. Expressed
# as SNR, not as a fraction of the peak: the peak is one hot pixel, so a
# fraction-of-peak threshold means nothing and, tried at 0.10, excluded every
# real star.
_MIN_SNR = 40.0
_ISOLATION = 14         # px; no other detection within this radius
_MATCH_TOL = 3.0        # px, after the global transform is solved

OS = 4                  # PSF oversampling factor
HALF = 8                # stamp half-width, original px
APER = 6.0              # fixed aperture for the half-light measure, original px
_JACK = 8               # jackknife subsets, for the error bar

_yy, _xx = np.mgrid[-HALF:HALF + 1, -HALF:HALF + 1]
_R = np.hypot(_xx, _yy)
_ANN = (_R >= 6.5) & (_R <= 8.0)     # local background annulus


def _load_lum(path):
    from astropy.io import fits
    d = np.nan_to_num(fits.getdata(path).astype(np.float32))
    if d.ndim == 3:
        d = d.mean(axis=0) if d.shape[0] in (3, 4) else d.mean(axis=2)
    peak = float(d.max()) or 1.0
    return d / peak


def _detect(lum, limit=4000):
    import sep
    bkg = sep.Background(lum)
    sub = lum - bkg.back()
    objs = sep.extract(sub, 5.0, err=bkg.globalrms)
    objs = objs[np.argsort(-objs["flux"])][:limit]
    return sub, objs, float(bkg.globalrms)


def _isolated(objs, idx):
    d = np.hypot(objs["x"] - objs["x"][idx], objs["y"] - objs["y"][idx])
    return int((d < _ISOLATION).sum()) == 1


class _Shift:
    """A pure translation, with the same call shape as an astroalign transform."""

    def __init__(self, dx, dy):
        self.dx, self.dy = dx, dy
        self.rotation, self.scale = 0.0, 1.0
        self.translation = (dx, dy)

    def __call__(self, pts):
        pts = np.asarray(pts, dtype=float)
        return np.stack([pts[:, 0] + self.dx, pts[:, 1] + self.dy], axis=1)


def _vote_shift(a_objs, b_objs, top=400, bin_px=2.0):
    """Solve the translation between two star lists by voting.

    Every A-star paired with every B-star implies an offset; the true one is
    voted for by many pairs and everything else scatters. Robust to the two
    images detecting different stars, which is exactly what defeats triangle
    matching here: astroalign needs the same stars inside its brightest-N, and
    noise reorders the flux ranking enough to break that.

    `top` is deliberately generous for the same reason.
    """
    ax, ay = a_objs["x"][:top], a_objs["y"][:top]
    bx, by = b_objs["x"][:top], b_objs["y"][:top]
    dx = (bx[None, :] - ax[:, None]).ravel()
    dy = (by[None, :] - ay[:, None]).ravel()
    keep = (np.abs(dx) < 2000) & (np.abs(dy) < 2000)
    dx, dy = dx[keep], dy[keep]
    if dx.size == 0:
        return None
    qx = np.round(dx / bin_px).astype(int)
    qy = np.round(dy / bin_px).astype(int)
    keys, counts = np.unique(np.stack([qx, qy], axis=1), axis=0, return_counts=True)
    best = keys[int(np.argmax(counts))]
    sel = (qx == best[0]) & (qy == best[1])
    return _Shift(float(np.median(dx[sel])), float(np.median(dy[sel]))), int(counts.max())


def _match_flip(lb, a_objs):
    """Return B row-flipped if that is how it matches A, else B unchanged.

    Two programs can disagree about FITS row order, and Nocturne and Siril DO:
    on the M 45 masters their star fields are vertical mirrors of each other.
    A reflection is not a rotation, so neither translation voting nor
    astroalign's triangle matching can absorb it — both simply fail, and the
    failure reads as "these are different fields" rather than "one is upside
    down". Resolve it before solving the transform.
    """
    _, ob, _ = _detect(lb)
    plain = _vote_shift(a_objs, ob)
    flipped_lum = np.ascontiguousarray(lb[::-1])
    _, ob_f, _ = _detect(flipped_lum)
    flipped = _vote_shift(a_objs, ob_f)
    n_plain = plain[1] if plain else 0
    n_flip = flipped[1] if flipped else 0
    if n_flip > n_plain * 2:
        return flipped_lum, True, (n_plain, n_flip)
    return lb, False, (n_plain, n_flip)


def _solve_transform(a_objs, b_objs):
    """Map A's pixel coordinates into B's."""
    got = _vote_shift(a_objs, b_objs)
    if got is not None and got[1] >= 12:
        return got[0], f"shift ({got[0].dx:+.1f}, {got[0].dy:+.1f}) px, {got[1]} votes"
    import astroalign
    n = min(200, len(a_objs), len(b_objs))
    src = np.stack([a_objs["x"][:n], a_objs["y"][:n]], axis=1)
    dst = np.stack([b_objs["x"][:n], b_objs["y"][:n]], axis=1)
    tf, _ = astroalign.find_transform(src, dst)
    return tf, (f"rot {np.degrees(tf.rotation):+.3f} deg, scale {tf.scale:.5f}, "
                f"shift {tf.translation[0]:+.1f} {tf.translation[1]:+.1f} px")


def stack_at(img, xs, ys, rms):
    """Oversampled PSF stacked at GIVEN positions — never re-detected."""
    n = 2 * HALF * OS + 1
    acc = np.zeros((n, n))
    cnt = np.zeros((n, n))
    used = 0
    h, w = img.shape
    for x, y in zip(xs, ys):
        xi, yi = int(round(x)), int(round(y))
        if not (HALF <= xi < w - HALF and HALF <= yi < h - HALF):
            continue
        cut = img[yi - HALF:yi + HALF + 1, xi - HALF:xi + HALF + 1].astype(np.float64)
        # Local background: M 45 sits in reflection nebulosity, and the global
        # subtraction leaves a structured pedestal under most stars.
        cut = cut - np.median(cut[_ANN])
        peak = cut.max()
        if peak > _MAX_PEAK or peak < _MIN_SNR * rms:
            continue
        flux = cut[_R <= APER].sum()
        if flux <= 0:
            continue
        # Normalised by its own flux so bright stars do not dominate the shape,
        # then dropped in at its sub-pixel offset. No interpolation: the phase
        # diversity across many stars does the resampling.
        gx = np.round((_xx + (xi - x)) * OS).astype(int) + n // 2
        gy = np.round((_yy + (yi - y)) * OS).astype(int) + n // 2
        ok = (gx >= 0) & (gx < n) & (gy >= 0) & (gy < n)
        np.add.at(acc, (gy[ok], gx[ok]), (cut / flux)[ok])
        np.add.at(cnt, (gy[ok], gx[ok]), 1.0)
        used += 1
    return np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan), used


def half_light(psf, step=0.02):
    """Half-light radius in ORIGINAL px, about the PSF's own centroid.

    Azimuthally averaged on a fine grid. Measured on the raw oversampled shells
    instead, the answer quantises to ~10% steps and silently returns identical
    readings for quite different inputs. Re-centring means a residual sub-pixel
    registration offset shifts the PSF rather than inflating its radius.
    """
    n = psf.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    v = np.where(np.isfinite(psf), np.clip(psf, 0, None), 0.0)
    c = n // 2
    near = np.hypot(xx - c, yy - c) <= 2.5 * OS
    tot = v[near].sum()
    if tot <= 0:
        return None
    cx = (v * xx)[near].sum() / tot
    cy = (v * yy)[near].sum() / tot
    r = np.hypot(xx - cx, yy - cy) / OS
    good = np.isfinite(psf) & (r <= APER)
    edges = np.arange(0, APER + step, step)
    nb = len(edges) - 1
    idx = np.clip(np.digitize(r[good], edges) - 1, 0, nb - 1)
    sums = np.bincount(idx, weights=np.clip(psf[good], 0, None), minlength=nb)[:nb]
    cnts = np.bincount(idx, minlength=nb)[:nb].astype(float)
    mean = np.where(cnts > 0, sums / np.maximum(cnts, 1), np.nan)
    mid = 0.5 * (edges[:-1] + edges[1:])
    ok = np.isfinite(mean)
    mean = np.interp(mid, mid[ok], mean[ok])
    flux = np.cumsum(mean * 2 * np.pi * mid * step)
    return float(np.interp(0.5 * flux[-1], flux, mid))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    pa, pb = sys.argv[1], sys.argv[2]
    la, lb = _load_lum(pa), _load_lum(pb)
    print(f"A {pa.rsplit('/', 1)[-1]}   {la.shape[1]}x{la.shape[0]}")
    print(f"B {pb.rsplit('/', 1)[-1]}   {lb.shape[1]}x{lb.shape[0]}\n")

    sa, oa, rms_a = _detect(la)
    lb, was_flipped, (n_plain, n_flip) = _match_flip(lb, oa)
    if was_flipped:
        print(f"B row-flipped to match A ({n_plain} votes as-is, {n_flip} flipped)"
              " — the two programs disagree about FITS row order\n")
    sb, ob, rms_b = _detect(lb)
    try:
        tf, how = _solve_transform(oa, ob)
    except Exception as exc:
        print(f"could not align the two star fields: {type(exc).__name__}: {exc}")
        return 1
    print(f"detected {len(oa)} / {len(ob)} stars; aligned by {how}")

    # Common star list: isolated in A, present and isolated in B. Positions come
    # from A alone; B is sampled at those positions mapped through tf.
    ax, ay, bx, by = [], [], [], []
    for i in range(len(oa)):
        if not _isolated(oa, i):
            continue
        tx, ty = tf(np.array([[oa["x"][i], oa["y"][i]]]))[0]
        d = np.hypot(ob["x"] - tx, ob["y"] - ty)
        j = int(np.argmin(d))
        if d[j] > _MATCH_TOL or not _isolated(ob, j):
            continue
        ax.append(oa["x"][i]); ay.append(oa["y"][i])
        bx.append(tx); by.append(ty)
    ax, ay, bx, by = map(np.asarray, (ax, ay, bx, by))
    if len(ax) < 100:
        print(f"\nonly {len(ax)} matched isolated stars — not enough to conclude.")
        return 1

    pa_psf, na = stack_at(sa, ax, ay, rms_a)
    pb_psf, nb = stack_at(sb, bx, by, rms_b)
    ha, hb = half_light(pa_psf), half_light(pb_psf)
    if ha is None or hb is None:
        print("\ncould not measure a stacked PSF.")
        return 1

    # Jackknife over star subsets: the scatter tells us whether a difference is
    # real or is just which stars happened to be used.
    rng = np.random.default_rng(0)
    order = rng.permutation(len(ax))
    ratios = []
    for k in range(_JACK):
        sel = order[k::_JACK]
        qa, _ = stack_at(sa, ax[sel], ay[sel], rms_a)
        qb, _ = stack_at(sb, bx[sel], by[sel], rms_b)
        va, vb = half_light(qa), half_light(qb)
        if va and vb:
            ratios.append(vb / va)
    ratios = np.array(ratios)

    print(f"\n{len(ax)} matched isolated stars; {na} / {nb} entered the stacks\n")
    print(f"  A half-light radius   {ha:.4f} px")
    print(f"  B half-light radius   {hb:.4f} px")
    ratio = hb / ha
    sem = ratios.std(ddof=1) / np.sqrt(len(ratios)) if len(ratios) > 1 else float("nan")
    print(f"\n  RATIO B/A  {ratio:.4f}  ({(ratio - 1) * 100:+.2f}%)"
          f"   jackknife sem {sem * 100:.2f}%")
    pct = (ratio - 1) * 100
    if abs(pct) < 1.0:
        print(f"  -> no difference above the {1.0:.1f}% floor of this metric")
    else:
        print(f"  -> {'B' if pct > 0 else 'A'} is softer by {abs(pct):.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
