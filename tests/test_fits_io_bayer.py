import numpy as np
from astropy.io import fits
from nocturne.core.fits_io import _bayer_pattern, load_fits


def test_bayer_pattern_reads_header():
    hdr = fits.Header()
    hdr["BAYERPAT"] = "GRBG"
    assert _bayer_pattern(hdr) == "GRBG"


def test_bayer_pattern_falls_back_when_missing_or_invalid():
    assert _bayer_pattern(fits.Header()) == "GRBG"          # instrument default
    bad = fits.Header()
    bad["BAYERPAT"] = "XYZW"
    assert _bayer_pattern(bad) == "GRBG"


def test_load_fits_debayers_with_header_pattern(tmp_path):
    # Construct a raw CFA frame where only the GREEN sites of a GRBG mosaic are
    # bright. GRBG layout (top-left origin): [0,0]=G [0,1]=R [1,0]=B [1,1]=G.
    cfa = np.zeros((8, 8), np.float32)
    cfa[0::2, 0::2] = 1000.0   # G
    cfa[1::2, 1::2] = 1000.0   # G
    p = tmp_path / "grbg.fit"
    hdr = fits.Header()
    hdr["BAYERPAT"] = "GRBG"
    fits.PrimaryHDU(cfa.astype(np.uint16), header=hdr).writeto(str(p))

    img = load_fits(str(p), normalize=False).data
    r, g, b = img[..., 0].mean(), img[..., 1].mean(), img[..., 2].mean()
    # Correct GRBG demosaic -> green dominates; red/blue stay far below it.
    #
    # Compared as a RATIO, not against an absolute level, so the test survives a
    # change of demosaic. What it exists to catch is a one-phase error, which is
    # what produces a green maze and false colour; how much a given algorithm
    # leaks between channels is a property of the algorithm, not a fault.
    # Measured with a gradient-corrected demosaic the leak was ~16% against
    # bilinear's ~7%, while a WRONG pattern gives R/G 6.88 against 0.16 correct
    # — a 43x separation either way.
    assert g > 500.0
    assert r < 0.25 * g and b < 0.25 * g


def _bayer_star_scene(h=120, w=120, sigma=1.1, seed=0, scale=40000.0):
    """A star field and the GRBG mosaic a sensor would sample from it.

    sigma 1.1 px matches the real M 45 subs, which is the point: the demosaic's
    softness only shows on stars near the sampling limit. A broad synthetic star
    is reconstructed equally well by every algorithm and would prove nothing.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    scene = np.full((h, w), 0.02, np.float32)
    for _ in range(25):
        cy, cx = rng.uniform(12, h - 12), rng.uniform(12, w - 12)
        scene = scene + 0.8 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    return (scene * scale).astype(np.float32)


def _write_bayer(path, cfa):
    hdr = fits.Header()
    hdr["BAYERPAT"] = "GRBG"
    fits.PrimaryHDU(cfa.astype(np.uint16), header=hdr).writeto(str(path))
    return str(path)


def test_debayer_does_not_invent_colour_on_stars(tmp_path):
    """The demosaic must not paint colour onto a neutral star.

    This is the guard on the Malvar2004 experiment of 2026-08-18. Malvar is
    genuinely sharper (21.7% on real subs) but puts a four-fold coloured cross
    around every star, aligned with the 2x2 Bayer grid: it infers red and blue
    from the green gradient, and at a star spanning ~2.6 px — near the CFA
    sampling limit — that inference rings along the CFA axes. It shipped, and
    Andreas spotted it on the first real stack.

    Every star in this fixture is NEUTRAL, so any colour in the result was
    invented by the demosaic. Measured ring colour error (max |R-G|/L + |B-G|/L
    at radius 1.5-3.5 px): bilinear 1.08 median / 1.16 max, Malvar2004 9.15
    median / 85.40 max. The gate at 3.0 sits far from both.

    A sharper demosaic is still wanted — but it has to pass THIS, not just a
    sharpness measure. The previous guard here checked only peak retention, so
    it passed happily while the output was covered in false colour.
    """
    scene = _bayer_star_scene(h=160, w=160)
    p = _write_bayer(tmp_path / "neutral.fit", scene)

    rgb = load_fits(p, normalize=False).data.astype(np.float64)
    lum = np.maximum(rgb.mean(axis=2), 1e-9)
    dev = (np.abs(rgb[..., 0] - rgb[..., 1]) + np.abs(rgb[..., 2] - rgb[..., 1])) / lum

    yy, xx = np.mgrid[-4:5, -4:5]
    rr = np.hypot(xx, yy)
    ring = (rr >= 1.5) & (rr <= 3.5)
    ys, xs = np.nonzero(scene > 0.5 * scene.max())
    worst = max(dev[y-4:y+5, x-4:x+5][ring].max()
                for y, x in zip(ys, xs) if 4 <= y < 156 and 4 <= x < 156)
    assert worst < 3.0, (
        f"demosaic invented colour around neutral stars: {worst:.2f}; "
        "bilinear scores ~1.2, a gradient-corrected demosaic ~9 and up"
    )
