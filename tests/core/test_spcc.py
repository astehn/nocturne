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


# ---- The sky must come off before the star is summed (2026-10-10) ----------
# On his masters the sky plus bias (~0.02, equal in R, G and B) was 93-99% of
# the light in each aperture, so every star read as nearly white and the gains
# came out ~1.00 on every image. Only a STARS-ONLY cast can catch that: a
# whole-image cast scales the pedestal with the stars and stays recoverable.

_PED = 0.02


def _faint_field(k=(1.0, 1.0, 1.0), ped=_PED, n=120, seed=1):
    """Faint stars of known colour on a grey sky pedestal plus noise, then a
    cast applied to the starlight only: ped + (img - ped) * k."""
    rng = np.random.default_rng(seed)
    h, w = 300, 360
    wcs = _wcs(w, h)
    from nocturne.tools.astap import FITS_Y_DOWN
    yy, xx = np.mgrid[0:h, 0:w]
    stars = np.zeros((h, w, 3), np.float32)
    gaia = []
    for _ in range(n):
        px, py = rng.uniform(20, w - 20), rng.uniform(20, h - 20)
        bp_rp = float(rng.uniform(-0.2, 2.5))
        g = float(rng.uniform(0.006, 0.02))         # faint: the sky is most of the aperture
        r = g * 10 ** (0.30 * (bp_rp - 0.82))
        b = g * 10 ** (-0.30 * (bp_rp - 0.82))
        blob = np.exp(-(((yy - py) ** 2 + (xx - px) ** 2) / (2 * 1.6 ** 2)))
        for c, amp in enumerate((r, g, b)):
            stars[..., c] += amp * blob
        py_fits = (h - 1 - py) if FITS_Y_DOWN else py
        sky = wcs.pixel_to_world(px, py_fits)
        gaia.append(GaiaStar(float(sky.ra.deg), float(sky.dec.deg), bp_rp, 10.0))
    noise = rng.normal(0.0, 0.0008, (h, w, 3)).astype(np.float32)
    data = ped + stars * np.array(k, np.float32) + noise
    return AstroImage(np.clip(data, 0, 1).astype(np.float32), is_linear=True), wcs, gaia


def _recovery(k):
    """Share of a stars-only cast the gains undo, per channel against green,
    in log space (1.0 = the whole cast)."""
    base = photometric_gains(*_faint_field())
    cast = photometric_gains(*_faint_field(k=k))
    assert base is not None and cast is not None
    out = []
    for c in (0, 2):
        found = np.log((cast.gains[c] / cast.gains[1]) / (base.gains[c] / base.gains[1]))
        want = -np.log(k[c] / k[1])
        out.append(found / want)
    return out


def test_stars_only_cast_is_recovered_through_a_sky_pedestal():
    for k in [(1.25, 1.0, 0.8), (0.85, 1.0, 1.2)]:
        rec_r, rec_b = _recovery(k)
        assert 0.9 <= rec_r <= 1.1, (k, rec_r)
        assert 0.9 <= rec_b <= 1.1, (k, rec_b)


def test_fitted_slopes_are_the_instrument_model_through_a_pedestal():
    res = photometric_gains(*_faint_field())
    sR, sB = res.slopes
    assert abs(sR - 0.30) < 0.05 and abs(sB + 0.30) < 0.05, res.slopes


def test_no_pedestal_frame_still_calibrates():
    res = photometric_gains(*_faint_field(ped=0.0))
    assert res is not None and res.n_matched >= 30
    sR, sB = res.slopes
    assert abs(sR - 0.30) < 0.05 and abs(sB + 0.30) < 0.05, res.slopes


# ---- Real data (bench-only) -------------------------------------------------
# Point NOCTURNE_SPCC_BENCH at the study's cache folder (<NAME>.pkl holding the
# plate solve and Gaia list per master) to run it; his master is read, never
# written. Expected gains: the 2026-10-10 study, sky subtracted.
import os  # noqa: E402

import pytest  # noqa: E402

_SPCC_BENCH = os.environ.get("NOCTURNE_SPCC_BENCH")
_M45 = "/Volumes/Work/Astro/M 45/Stacked_304_M 45_10.0s_IRCUT_20260810-045011.fit"


def test_his_m45_gains_match_the_sky_subtracted_study():
    if not _SPCC_BENCH:
        pytest.skip("bench-only: set NOCTURNE_SPCC_BENCH to the SPCC study cache folder")
    import pickle
    cache = os.path.join(_SPCC_BENCH, "M_45.pkl")
    if not (os.path.exists(cache) and os.path.exists(_M45)):
        pytest.skip(f"bench-only: {cache} or {_M45} not found")
    from nocturne.core.fits_io import load_fits
    wcs, gaia, _src, _scale = pickle.load(open(cache, "rb"))
    res = photometric_gains(load_fits(_M45), wcs, gaia)
    assert res is not None
    for got, want in zip(res.gains, (0.7943, 1.0667, 1.1802)):
        assert abs(got - want) <= 0.03, res.gains
