import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.hdr import recover_core


def _blob():
    """A bright, near-flat core (0.88) with a fine high-frequency ripple, on a
    dark background (0.2). The ripple is the 'structure' that should survive the
    blur into the detail layer and be re-expanded."""
    h = w = 200
    lum = np.full((h, w), 0.2, np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    ripple = 0.04 * np.sin(2 * np.pi * xx / 3.0).astype(np.float32)  # period 3px
    core = slice(60, 140)
    lum[core, core] = 0.88 + ripple[core, core]
    return AstroImage(np.repeat(lum[:, :, None], 3, axis=2).astype(np.float32),
                      is_linear=False)


def _interior(arr):
    """Central patch of the core, away from its edges (blur bleed / mask ramp)."""
    return arr[80:120, 80:120]


def test_amount_zero_is_noop():
    img = _blob()
    out = recover_core(img, 0.0).data
    assert np.allclose(out, img.data, atol=1e-6)


def test_lowers_core_and_raises_relative_contrast():
    img = _blob()
    out = recover_core(img, 0.8).data
    lum_in = img.data.mean(axis=2)
    lum_out = out.mean(axis=2)
    in_c, out_c = _interior(lum_in), _interior(lum_out)
    # Core mean pulled down.
    assert out_c.mean() < in_c.mean() - 0.02
    # Structure's relative contrast (std / mean) raised — detail re-expanded.
    assert out_c.std() / out_c.mean() > in_c.std() / in_c.mean()


def test_background_below_mask_is_untouched():
    img = _blob()
    out = recover_core(img, 0.8).data
    # A far corner, well below the highlight mask ramp — must be unchanged.
    assert np.allclose(out[:20, :20], img.data[:20, :20], atol=1e-6)


def test_output_stays_in_unit_range():
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((64, 64, 3)).astype(np.float32), is_linear=False)
    out = recover_core(img, 1.0).data
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_preserves_is_linear_and_metadata():
    img = AstroImage(np.full((32, 32, 3), 0.9, np.float32),
                     is_linear=False, metadata={"k": 1})
    out = recover_core(img, 0.5)
    assert out.is_linear is False
    assert out.metadata == {"k": 1}


def test_greyscale_path():
    lum = np.full((64, 64), 0.9, np.float32)
    lum[20:44, 20:44] += 0.03 * np.sin(np.arange(64) / 2.0)[None, 20:44].repeat(24, 0)
    out = recover_core(AstroImage(lum), 0.7)
    assert out.data.ndim == 2
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
