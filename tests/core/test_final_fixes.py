import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.final_fixes import FinalFixesSettings, apply_final_fixes


def _none():
    return FinalFixesSettings(
        remove_green=False, saturation="None", increase_blue=False, sky="Normal"
    )


def test_all_off_is_noop():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    out = apply_final_fixes(img, _none())
    assert np.allclose(out.data, img.data)
    assert out.is_linear is False


def test_remove_green_reduces_green_excess():
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # strong green cast
    img = AstroImage(data, is_linear=False)
    s = _none()
    s.remove_green = True
    out = apply_final_fixes(img, s)
    assert out.data[..., 1].mean() < 0.8
    assert out.data[..., 1].max() <= (0.3 + 0.3) / 2 + 1e-6


def test_saturation_increases_channel_spread():
    data = np.tile(np.array([0.6, 0.4, 0.2], dtype=np.float32), (8, 8, 1))
    img = AstroImage(data, is_linear=False)
    s = _none()
    s.saturation = "Strong"
    out = apply_final_fixes(img, s)
    before = data[0, 0].max() - data[0, 0].min()
    after = out.data[0, 0].max() - out.data[0, 0].min()
    assert after > before


def test_increase_blue_raises_blue_mean():
    data = np.full((8, 8, 3), 0.4, dtype=np.float32)
    img = AstroImage(data, is_linear=False)
    s = _none()
    s.increase_blue = True
    out = apply_final_fixes(img, s)
    assert out.data[..., 2].mean() > 0.4


def test_darker_sky_lowers_median():
    data = np.full((8, 8, 3), 0.35, dtype=np.float32)
    img = AstroImage(data, is_linear=False)
    s = _none()
    s.sky = "Darker"
    out = apply_final_fixes(img, s)
    assert np.median(out.data) < 0.35


def test_lighter_sky_raises_median():
    data = np.full((8, 8, 3), 0.35, dtype=np.float32)
    img = AstroImage(data, is_linear=False)
    s = _none()
    s.sky = "Lighter"
    out = apply_final_fixes(img, s)
    assert np.median(out.data) > 0.35


def test_mono_only_applies_sky():
    img = AstroImage(np.full((8, 8), 0.35, dtype=np.float32), is_linear=False)
    s = FinalFixesSettings(remove_green=True, saturation="Strong",
                           increase_blue=True, sky="Darker")
    out = apply_final_fixes(img, s)
    assert out.data.ndim == 2
    assert np.median(out.data) < 0.35  # sky still applied; color ops skipped safely


def test_output_float32_clipped():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    s = FinalFixesSettings(remove_green=True, saturation="Strong",
                           increase_blue=True, sky="Lighter")
    out = apply_final_fixes(img, s)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
