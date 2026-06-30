import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.stretch import apply_stretch, amount_to_target


def _faint():
    rng = np.random.default_rng(0)
    data = np.clip(rng.normal(0.003, 0.0008, (64, 64, 3)), 0, 1).astype(np.float32)
    data[20:40, 20:40] += 0.02  # faint nebula
    data[0, 0] = 1.0            # a bright star driving the max
    return AstroImage(data)


def test_stretch_marks_nonlinear():
    out = apply_stretch(_faint(), 0.5)
    assert out.is_linear is False
    assert out.data.dtype == np.float32


def test_stretch_lifts_faint_background():
    out = apply_stretch(_faint(), 0.5)
    # adaptive stretch must lift the background well above the raw ~0.003
    assert np.median(out.data) > 0.15


def test_larger_amount_brightens_more():
    img = _faint()
    low = np.median(apply_stretch(img, 0.1).data)
    high = np.median(apply_stretch(img, 0.9).data)
    assert high > low


def test_amount_clamped():
    assert amount_to_target(-1) == amount_to_target(0.0)
    assert amount_to_target(5) == amount_to_target(1.0)


def test_output_in_range():
    out = apply_stretch(_faint(), 1.0)
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
