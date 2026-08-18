"""Compare two masters' star sharpness with a FLUX-INDEPENDENT metric.

    compare_masters.py NOCTURNE.fits SIRIL.fits

Why not just use sep's FWHM, as before: sep reports isophotal moments, and an
isophote grows with signal-to-noise. A deeper or better-stretched image measures
every star broader for reasons that have nothing to do with sharpness. That
invalidated an earlier claim in this project ("stacking degrades stars 11%") and
it is why the M 31 Nocturne-vs-Siril comparison could never be settled.

What this does instead:

1. Detect stars in both images independently.
2. CROSS-MATCH them by position, after solving the offset between the two
   images, so every comparison is the SAME physical star in both.
3. Fit a 2-D Gaussian to each matched star in each image and compare the fitted
   sigma. A Gaussian fit is bounded by the profile's shape, not by where an
   isophote happens to fall, so it does not drift with depth.
4. Report the paired difference, which removes star-to-star variation entirely —
   the same star is its own control.

Only stars that are unsaturated, isolated and well-fitted in BOTH images are
used, because a saturated core has no Gaussian to fit and a blended pair
measures the blend.

VALIDATED against known answers before use, 2026-08-18:

    identical images        expected 1.0000   measured 1.0000
    a known 0.8 px blur     expected 1.1976   measured 1.2018  (0.4% error)
                            and 114 of 114 stars agreed individually

KNOWN LIMITATION: the two images must have comparable NOISE. The SNR gate picks
a different star population out of a much noisier image, and on a copy with
sqrt(2) the noise and identical sharpness an earlier, looser version reported
3.3% of spurious softness. Feed both programs the SAME frame list — which is
also required for the FWHM numbers to mean anything — and this does not arise.
"""
import sys

import numpy as np  # noqa: E402

_MAX_PEAK = 0.95        # a clipped core cannot be fitted
# A star must rise this far above the background NOISE to be fitted. Expressed
# as SNR, not as a fraction of the peak: the peak is one hot pixel, so a
# fraction-of-peak threshold means nothing and, tried at 0.10, excluded every
# real star. Set after measuring the instrument against itself — faint stars
# gave wild fits on a noisier copy and manufactured 3.3% of "softness" out of
# noise alone.
_MIN_SNR = 40.0
_BOX = 11               # fitting box half-width in pixels
_ISOLATION = 14         # no other detection within this radius
_MATCH_TOL = 3.0        # px, after the global offset is solved


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
    x, y = objs["x"][idx], objs["y"][idx]
    d = np.hypot(objs["x"] - x, objs["y"] - y)
    return int((d < _ISOLATION).sum()) == 1


def _fit_sigma(img, x, y, rms):
    """Least-squares 2-D Gaussian sigma for one star, or None if unfittable."""
    h, w = img.shape
    xi, yi = int(round(x)), int(round(y))
    if not (_BOX <= xi < w - _BOX and _BOX <= yi < h - _BOX):
        return None
    cut = img[yi - _BOX:yi + _BOX + 1, xi - _BOX:xi + _BOX + 1].astype(np.float64)
    peak = cut.max()
    if peak > _MAX_PEAK or peak < _MIN_SNR * rms:
        return None
    yy, xx = np.mgrid[-_BOX:_BOX + 1, -_BOX:_BOX + 1]
    # log-linear fit: log(I) = log(A) - (dx^2+dy^2)/(2 sigma^2)
    m = cut > peak * 0.15
    if m.sum() < 12:
        return None
    r2 = (xx[m] ** 2 + yy[m] ** 2).astype(np.float64)
    v = np.log(np.clip(cut[m], 1e-9, None))
    A = np.stack([np.ones_like(r2), r2], axis=1)
    try:
        coef, *_ = np.linalg.lstsq(A, v, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if coef[1] >= 0:
        return None                       # not a peak
    sigma = float(np.sqrt(-1.0 / (2.0 * coef[1])))
    if not (0.3 < sigma < 8.0):
        return None
    # Reject a poor fit outright. Without this, stars whose profile is buried in
    # noise still return a number, and those numbers are what turned a pure
    # noise difference into an apparent 3.3% softness.
    pred = A @ coef
    ss_res = float(((v - pred) ** 2).sum())
    ss_tot = float(((v - v.mean()) ** 2).sum()) or 1e-12
    if 1.0 - ss_res / ss_tot < 0.90:
        return None
    return sigma


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

    `top` is deliberately generous: noise reorders the flux ranking, so the two
    images' brightest-60 can be largely different stars and the vote starves.
    400 x 400 pairs is still trivial to compute.

    Every A-star paired with every B-star implies an offset; the true one is
    voted for by many pairs and everything else scatters. Robust to the two
    images detecting different stars, which is exactly what defeats triangle
    matching here: astroalign needs the same stars inside its brightest-N, and
    adding noise reorders the flux ranking enough to break that even on images
    that are pixel-identical.
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
    votes = int(counts.max())
    sel = (qx == best[0]) & (qy == best[1])
    return _Shift(float(np.median(dx[sel])), float(np.median(dy[sel]))), votes


def _solve_transform(a_objs, b_objs):
    """Map A's pixel coordinates into B's.

    Translation voting first, since two masters of one field differ by a shift
    and a crop. Falls back to astroalign for the case that genuinely needs
    rotation or scale. NOT a difference of medians, which was the first attempt
    and is meaningless when the images detect different stars — it produced
    offsets of -95 and +455 px on images that were actually aligned.
    """
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


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    pa, pb = sys.argv[1], sys.argv[2]
    la, lb = _load_lum(pa), _load_lum(pb)
    print(f"A {pa.rsplit('/',1)[-1]}   {la.shape[1]}x{la.shape[0]}")
    print(f"B {pb.rsplit('/',1)[-1]}   {lb.shape[1]}x{lb.shape[0]}\n")

    sa, oa, rms_a = _detect(la)
    sb, ob, rms_b = _detect(lb)
    try:
        tf, how = _solve_transform(oa, ob)
    except Exception as exc:
        print(f"\ncould not align the two star fields: {type(exc).__name__}: {exc}")
        return 1
    print(f"detected {len(oa)} / {len(ob)} stars; aligned by {how}")

    pairs = []
    bx, by = ob["x"], ob["y"]
    for i in range(len(oa)):
        if not _isolated(oa, i):
            continue
        tx, ty = tf(np.array([[oa["x"][i], oa["y"][i]]]))[0]
        d = np.hypot(bx - tx, by - ty)
        j = int(np.argmin(d))
        if d[j] > _MATCH_TOL or not _isolated(ob, j):
            continue
        ga = _fit_sigma(sa, oa["x"][i], oa["y"][i], rms_a)
        gb = _fit_sigma(sb, bx[j], by[j], rms_b)
        if ga and gb:
            pairs.append((ga, gb))

    if len(pairs) < 20:
        print(f"\nonly {len(pairs)} usable matched stars — not enough to conclude.")
        return 1

    a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
    ratio = b / a
    print(f"\n{len(pairs)} stars matched, isolated, unsaturated and fitted in BOTH\n")
    print(f"  A fitted sigma   median {np.median(a):.3f} px")
    print(f"  B fitted sigma   median {np.median(b):.3f} px")
    print(f"\n  PAIRED ratio B/A median {np.median(ratio):.4f}   "
          f"mean {ratio.mean():.4f} ± {ratio.std()/np.sqrt(len(ratio)):.4f} (sem)")
    pct = (np.median(ratio) - 1) * 100
    verdict = ("B is softer" if pct > 0 else "A is softer")
    print(f"  -> {verdict} by {abs(pct):.1f}%")
    # a paired sign test: how often is B wider than A?
    wins = int((b > a).sum())
    print(f"  B wider on {wins}/{len(pairs)} stars ({wins/len(pairs)*100:.0f}%) "
          f"— 50% would mean no difference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
