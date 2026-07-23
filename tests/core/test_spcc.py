import numpy as np
from astropy.wcs import WCS
from nocturne.core.image import AstroImage
from nocturne.core.spcc import photometric_gains, apply_gains, SpccResult
from nocturne.tools.gaia import GaiaStar


def _wcs(w, h, cra=100.0, cdec=0.0, scale=0.0005):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]; wc.wcs.crval = [cra, cdec]
    wc.wcs.cd = [[-scale, 0], [0, scale]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


def _star_field(cast=(1.0, 1.0, 1.0), n=100, seed=0):
    """A synthetic linear field of gaussian stars whose intrinsic colour tracks a
    known BP-RP, calibrated so a solar (BP-RP 0.82) star is neutral, then multiplied
    by `cast`. Returns (AstroImage, wcs, [GaiaStar]). The instrumental model:
    log10(R/G) = 0.30*(bp_rp-0.82), log10(B/G) = -0.30*(bp_rp-0.82)."""
    rng = np.random.default_rng(seed)
    h, w = 260, 320
    wcs = _wcs(w, h)
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    from nocturne.tools.astap import FITS_Y_DOWN
    yy, xx = np.mgrid[0:h, 0:w]
    data = np.zeros((h, w, 3), np.float32)
    gaia = []
    for _ in range(n):
        px, py = rng.uniform(20, w - 20), rng.uniform(20, h - 20)     # display-space pixel
        bp_rp = float(rng.uniform(-0.2, 2.5))
        g = 0.6
        r = g * 10 ** (0.30 * (bp_rp - 0.82))
        b = g * 10 ** (-0.30 * (bp_rp - 0.82))
        blob = np.exp(-(((yy - py) ** 2 + (xx - px) ** 2) / (2 * 1.6 ** 2)))
        for c, amp in enumerate((r, g, b)):
            data[..., c] += amp * cast[c] * blob
        py_fits = (h - 1 - py) if FITS_Y_DOWN else py
        sky = wcs.pixel_to_world(px, py_fits)
        gaia.append(GaiaStar(float(sky.ra.deg), float(sky.dec.deg), bp_rp, 10.0))
    return AstroImage(np.clip(data, 0, 1), is_linear=True), wcs, gaia


def test_photometric_gains_recovers_neutral_on_uncast_field():
    img, wcs, gaia = _star_field(cast=(1.0, 1.0, 1.0))
    res = photometric_gains(img, wcs, gaia)
    assert isinstance(res, SpccResult) and res.n_matched >= 30
    gR, gG, gB = res.gains
    assert abs(gR - gG) < 0.08 and abs(gB - gG) < 0.08          # already ~neutral


def test_photometric_gains_removes_a_known_cast():
    img, wcs, gaia = _star_field(cast=(1.4, 1.0, 0.7))          # red-heavy, blue-weak
    res = photometric_gains(img, wcs, gaia)
    assert res is not None
    gR, gG, gB = res.gains
    # gains should undo the cast: gR/gG ~ 1/1.4, gB/gG ~ 1/0.7 (ratios, brightness-normalised)
    assert (gR / gG) < 0.85 and (gB / gG) > 1.2


def test_photometric_gains_returns_none_below_min_stars():
    img, wcs, gaia = _star_field(n=60)
    assert photometric_gains(img, wcs, gaia[:5], min_stars=15) is None


def test_apply_gains_multiplies_and_clips():
    img = AstroImage(np.full((4, 4, 3), 0.5, np.float32), is_linear=True,
                     metadata={"target": "x"})
    out = apply_gains(img, (0.5, 1.0, 3.0))
    assert np.allclose(out.data[..., 0], 0.25)
    assert np.allclose(out.data[..., 2], 1.0)                   # 0.5*3=1.5 -> clipped
    assert out.metadata["target"] == "x" and out.is_linear is True
