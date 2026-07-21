import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.saturation import saturate, nebula_saturate
from nocturne.steps.saturation_step import SaturationStep


def _img():
    a = np.full((16, 16, 3), 0.12, np.float32)
    a[4:12, 4:12] = (0.6, 0.3, 0.3)
    return AstroImage(a, is_linear=False)


class _FakeRC:
    def __init__(self, starless, stars):
        self._s = (starless, stars)

    def remove_stars(self, img, runner=None):
        return self._s


def test_apply_combines_nebula_then_global():
    img = _img()
    starless = _img()
    stars = AstroImage(np.zeros((16, 16, 3), np.float32), is_linear=False)
    step = SaturationStep(_FakeRC(starless, stars))
    out = step.apply(img, (0.7, 0.6)).data
    expected = saturate(nebula_saturate(starless, stars, 0.6), 0.7).data
    assert np.allclose(out, expected)


def test_apply_legacy_float_is_global_only():
    img = _img()
    step = SaturationStep(_FakeRC(_img(), _img()))   # rc unused when nebula 0
    assert np.allclose(step.apply(img, 0.7).data, saturate(img, 0.7).data)


def test_apply_empty_option_is_native():
    img = _img()
    step = SaturationStep(_FakeRC(_img(), _img()))
    assert np.allclose(step.apply(img, "").data, saturate(img, 0.5).data)
