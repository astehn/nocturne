import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.crop import detect_content_bounds, auto_crop


def _bordered():
    data = np.zeros((40, 50, 3), dtype=np.float32)
    data[5:35, 8:45] = 0.4  # content rectangle inside a black border
    return AstroImage(data)


def test_detect_bounds_finds_content_rect():
    assert detect_content_bounds(_bordered()) == (5, 35, 8, 45)


def test_auto_crop_removes_border():
    out = auto_crop(_bordered())
    assert out.data.shape == (30, 37, 3)
    assert out.data.min() > 0.0


def test_auto_crop_extra_margin():
    out = auto_crop(_bordered(), margin=0.10)
    assert out.data.shape[0] < 30 and out.data.shape[1] < 37


def test_auto_crop_preserves_is_linear():
    img = AstroImage(_bordered().data, is_linear=True)
    assert auto_crop(img).is_linear is True


def test_detect_bounds_all_black_returns_full():
    img = AstroImage(np.zeros((10, 12), dtype=np.float32))
    assert detect_content_bounds(img) == (0, 10, 0, 12)


# --- uncovered area ----------------------------------------------------------

def test_a_full_frame_reports_no_uncovered_area():
    from nocturne.core.crop import uncovered_fraction
    assert uncovered_fraction(AstroImage(np.full((40, 40, 3), 0.3, np.float32))) == 0.0


def test_a_mosaic_with_black_wedges_reports_them():
    """An uncropped mosaic is mostly picture with ragged black corners. Fitting
    a background model over those corners is what makes the result unusable —
    GraXpert has no way to know they are not sky."""
    from nocturne.core.crop import uncovered_fraction
    data = np.full((100, 100, 3), 0.3, np.float32)
    data[:20, :] = 0.0                      # a fifth of the frame is uncovered
    assert 0.19 < uncovered_fraction(AstroImage(data)) < 0.21


def test_faint_real_sky_is_not_mistaken_for_uncovered():
    """Dark sky is not the same as no data. A threshold that counted genuinely
    dark pixels would warn on every well-exposed linear image."""
    from nocturne.core.crop import uncovered_fraction
    rng = np.random.default_rng(0)
    data = (rng.random((100, 100, 3)) * 0.004 + 0.001).astype(np.float32)
    assert uncovered_fraction(AstroImage(data)) == 0.0


def test_mono_images_are_handled():
    from nocturne.core.crop import uncovered_fraction
    data = np.full((50, 50), 0.3, np.float32)
    data[:10] = 0.0
    assert 0.19 < uncovered_fraction(AstroImage(data)) < 0.21
