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


def test_autostretch_neutralizes_color_cast():
    data = np.full((8, 8, 3), 0.05, dtype=np.float32)
    data[..., 1] *= 0.5  # green darker -> a colour cast
    out = autostretch(AstroImage(data.copy()))
    # autostretch is now per-channel (unlinked): the cast is NEUTRALIZED, so the
    # preview matches the neutral committed stretch (WYSIWYG), not a red-clipped view
    meds = [float(np.median(out[..., c])) for c in range(3)]
    assert max(meds) - min(meds) < 0.02


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


# --- non-finite robustness -------------------------------------------------
# One NaN pixel used to make the median AND the MAD NaN, so every pixel in that
# channel stretched to NaN and the canvas painted the whole channel black.

def test_one_nan_pixel_does_not_blank_the_channel():
    rng = np.random.default_rng(0)
    clean = (rng.random((20, 20, 3)) * 0.1).astype(np.float32)
    dirty = clean.copy()
    dirty[5, 5, 1] = np.nan

    out = unlinked_stretch(dirty)
    good = np.ones((20, 20), bool)
    good[5, 5] = False
    assert np.isfinite(out[..., 1][good]).all(), \
        "the 399 good pixels of the poisoned channel must survive one bad one"
    assert np.isfinite(out[..., 0]).all() and np.isfinite(out[..., 2]).all()


def test_a_nan_pixel_barely_perturbs_every_other_pixel():
    """The strong form: not merely 'finite', but essentially UNCHANGED. An
    implementation that dropped NaN by rescaling the channel would pass the
    finiteness check above while quietly altering all 399 other pixels.

    Not bit-identical, and it should not be: excluding the NaN sample shifts the
    median by one rank out of 400, so the derived transfer moves a hair.

    Tolerance measured, not guessed: this seed's delta is 9.4e-05, and the worst
    over 30 seeds is 2.0e-03 — so 2e-3 (the obvious round number) sits exactly ON
    the worst case and would flake the moment the seed changed. 5e-3 is that
    measured worst case with headroom. Anything approaching it means the good
    pixels are being altered, which is the failure this test exists to catch."""
    rng = np.random.default_rng(1)
    clean = (rng.random((20, 20, 3)) * 0.1).astype(np.float32)
    dirty = clean.copy()
    dirty[5, 5, 1] = np.nan

    before = unlinked_stretch(clean)
    after = unlinked_stretch(dirty)
    good = np.ones((20, 20), bool)
    good[5, 5] = False
    assert np.allclose(before[..., 1][good], after[..., 1][good], atol=5e-3)
    assert np.array_equal(before[..., 0], after[..., 0]), "other channels untouched"
    assert np.array_equal(before[..., 2], after[..., 2]), "other channels untouched"


def test_linked_stretch_survives_a_nan_in_one_channel():
    """linked_stretch derives ONE transfer from mean-across-channels luminance,
    so a NaN in any single channel used to poison all three."""
    rng = np.random.default_rng(2)
    data = (rng.random((16, 16, 3)) * 0.1).astype(np.float32)
    data[3, 3, 0] = np.nan
    out = linked_stretch(data, 0.25)
    good = np.ones((16, 16), bool)
    good[3, 3] = False
    for ch in range(3):
        assert np.isfinite(out[..., ch][good]).all(), f"channel {ch} was poisoned"


def test_an_all_nan_channel_yields_no_nan_parameters():
    """Nothing to measure. It must not raise, warn, or return NaN parameters.

    Mutation this must fail against: dropping the `isfinite(c).any()` early
    return while keeping np.nanmedian — nanmedian on an all-NaN slice warns
    ("All-NaN slice encountered") and returns NaN. Verified to fail without it.
    It does NOT catch a revert to plain np.median (that returns NaN silently);
    the three tests above cover that."""
    import warnings
    data = np.full((8, 8, 3), 0.1, np.float32)
    data[..., 1] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        out = unlinked_stretch(data)
    assert np.isfinite(out[..., 0]).all() and np.isfinite(out[..., 2]).all()
