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
    # Compared as a RATIO, not against an absolute level. Malvar2004 is
    # gradient-corrected bilinear: it feeds the green gradient into the red and
    # blue estimate, which is where its sharpness comes from, so an all-green
    # synthetic mosaic leaks ~16% into R/B where plain bilinear leaked ~7%. That
    # leak is the algorithm working, not a phase error, and an absolute
    # threshold would police the wrong thing.
    #
    # The ratio keeps the teeth that matter — a one-phase error is what produces
    # a green maze and false colour. Measured on this fixture: correct pattern
    # R/G 0.16, wrong pattern (RGGB or BGGR) R/G 6.88, a 43x separation.
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


def test_debayer_preserves_star_sharpness(tmp_path):
    """The demosaic must not blur stars away.

    Nocturne shipped `demosaicing_CFA_Bayer_bilinear`, and on real M 45 data
    that measured 21.7% softer than Malvar2004 over a common 417-star subset —
    about half of why a Nocturne master was 17.7% softer than Siril's from the
    SAME 266 subs (2026-08-18).

    Measured peak retention on this fixture: bilinear 75.9%, Malvar2004 105.4%
    (over 100% because Malvar overshoots slightly, which is the ringing the
    clip below handles). The 0.90 gate sits between them, so it fails if the
    demosaic is ever swapped back to a blurring one.
    """
    scene = _bayer_star_scene()
    p = _write_bayer(tmp_path / "stars.fit", scene)

    lum = load_fits(p, normalize=False).data.mean(axis=2)
    retained = lum.max() / scene.max()
    assert retained > 0.90, (
        f"demosaic lost star peak: retained {retained:.3f} of the scene peak; "
        "bilinear scores ~0.76 here"
    )


def test_debayer_never_returns_negative_pixels(tmp_path):
    """A sharpening demosaic rings, and flux cannot be negative.

    Malvar2004 has negative filter lobes, so around a saturated core it
    undershoots — measured on a real M 45 sub: 649 pixels below zero, the worst
    at -7264 ADU. The existing clip only runs when normalize=True, and the whole
    stacking path loads with normalize=False, so without a floor those values go
    straight into the stack and can poison a later log or sqrt stretch.
    """
    cfa = np.full((60, 60), 300.0, np.float32)
    cfa[28:32, 28:32] = 65535.0          # saturated core -> strong ringing
    p = _write_bayer(tmp_path / "sat.fit", cfa)

    data = load_fits(p, normalize=False).data
    assert data.min() >= 0.0, f"demosaic produced {(data < 0).sum()} negative pixels"
