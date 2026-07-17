import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.autostretch import autostretch, _TARGET_BG, linked_stretch, unlinked_stretch


def test_autostretch_brightens_dark_image_without_mutating():
    data = np.full((8, 8), 0.02, dtype=np.float32)
    data[0, 0] = 0.9
    img = AstroImage(data.copy())
    out = autostretch(img)
    assert out.shape == data.shape
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0
    # median should be lifted well above the original 0.02
    assert np.median(out) > 0.1
    # original image is untouched
    assert np.allclose(img.data, data)


def test_linked_autostretch_preserves_color_ratio():
    data = np.full((8, 8, 3), 0.05, dtype=np.float32)
    data[..., 1] *= 0.5  # green darker -> a colour cast
    out = autostretch(AstroImage(data.copy()))
    # linked stretch keeps green below red (cast preserved, not neutralized)
    assert out[..., 1].mean() < out[..., 0].mean() - 1e-3


def test_autostretch_color_does_not_mutate():
    data = np.full((8, 8, 3), 0.02, dtype=np.float32)
    data[0, 0, :] = 0.9
    img = AstroImage(data.copy())
    out = autostretch(img)
    assert out.shape == (8, 8, 3)
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0
    # each channel's median is lifted above the original 0.02
    for ch in range(3):
        assert np.median(out[..., ch]) > 0.1
    # original image is untouched
    assert np.allclose(img.data, data)


def _cast_image(offsets=(0.05, 0.12, 0.4), seed=0):
    """Synthetic linear frame with a strong per-channel sky offset (blue cast)."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 0.004, size=(64, 64)).astype(np.float32)
    return np.stack([np.clip(base + o, 0.0, 1.0) for o in offsets], axis=2)


def test_unlinked_stretch_neutralizes_cast():
    out = unlinked_stretch(_cast_image())
    meds = [float(np.median(out[..., c])) for c in range(3)]
    for m in meds:
        assert abs(m - _TARGET_BG) < 0.02      # every channel hits the target bg


def test_linked_stretch_keeps_cast_for_contrast():
    # sanity: the linked stretch (editor display) preserves the imbalance,
    # proving unlinked is doing the neutralizing, not the test fixture
    out = linked_stretch(_cast_image(), _TARGET_BG)
    meds = [float(np.median(out[..., c])) for c in range(3)]
    assert max(meds) - min(meds) > 0.1


def test_unlinked_stretch_2d_delegates_to_linked():
    mono = _cast_image()[..., 0]
    np.testing.assert_allclose(unlinked_stretch(mono),
                               linked_stretch(mono, _TARGET_BG))


def test_unlinked_stretch_constant_channel_does_not_crash():
    img = _cast_image()
    img[..., 2] = 0.0                          # dead channel
    out = unlinked_stretch(img)
    assert np.isfinite(out).all()
    assert out.shape == img.shape


def test_unlinked_stretch_constant_nonzero_channel_is_finite():
    img = _cast_image()
    img[..., 2] = 0.3                          # flat nonzero channel
    out = unlinked_stretch(img)
    assert np.isfinite(out).all()
    assert abs(float(np.median(out[..., 2])) - _TARGET_BG) < 0.02
