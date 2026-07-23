import numpy as np
from astropy.wcs import WCS
from nocturne.core.image import AstroImage
from nocturne.core.color import ColorSettings
from nocturne.steps.color import ColorStep
from nocturne.tools.astap import SolveResult
from nocturne.tools.gaia import GaiaStar, GaiaError


def _img():
    rng = np.random.default_rng(0)
    return AstroImage(rng.random((40, 40, 3)).astype(np.float32), is_linear=True,
                      metadata={"focal_length": 160.0, "pixel_size": 2.9})


class _FakeAstap:
    def __init__(self, solved=True):
        wc = WCS(naxis=2); wc.wcs.crpix = [20, 20]; wc.wcs.crval = [100.0, 0.0]
        wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        self._res = SolveResult(solved, wc if solved else None, 100.0, 0.0, 3.6)
    def solve(self, img, **kw):
        return self._res


def test_sky_method_uses_apply_color():
    out = ColorStep().apply(_img(), ColorSettings(method="sky"))
    assert out.data.shape == (40, 40, 3)                     # no crash, no astap needed


def test_photometric_falls_back_to_sky_when_gaia_unreachable():
    def boom(*a, **k):
        raise GaiaError("no network")
    step = ColorStep(astap=_FakeAstap(), gaia_query=boom)
    out = step.apply(_img(), ColorSettings(method="photometric"))
    assert out.data.shape == (40, 40, 3)                     # fell back, no error
    assert "sky balance" in step.last_message.lower()


def test_photometric_falls_back_when_solve_fails():
    step = ColorStep(astap=_FakeAstap(solved=False),
                     gaia_query=lambda *a, **k: [GaiaStar(100.0, 0.0, 0.8, 10.0)])
    out = step.apply(_img(), ColorSettings(method="photometric"))
    assert out.data.shape == (40, 40, 3)
    assert step.last_message                                 # a fallback reason is set


def test_photometric_no_astap_configured_falls_back():
    step = ColorStep(astap=None, gaia_query=lambda *a, **k: [])
    out = step.apply(_img(), ColorSettings(method="photometric"))
    assert out.data.shape == (40, 40, 3) and step.last_message
