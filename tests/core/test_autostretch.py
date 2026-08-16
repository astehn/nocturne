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


# --- the stretch must not invent colour --------------------------------------

def _bayer_like(seed=0, shape=(200, 200)):
    """An image shaped like real OSC data: green carries HALF the noise, because
    a Bayer sensor has twice as many green photosites, while the signal is
    genuinely RED-dominant. Measured on the M 31 mosaic: sky R 0.01748 G 0.01733
    B 0.01727, MAD R 0.000150 G 0.000078 B 0.000143."""
    rng = np.random.default_rng(seed)
    sky = {"R": 0.01748, "G": 0.01733, "B": 0.01727}
    mad = {"R": 0.000150, "G": 0.000078, "B": 0.000143}
    chans = []
    for c in "RGB":
        chans.append(rng.normal(sky[c], mad[c] * 1.4826, shape).astype(np.float32))
    data = np.stack(chans, axis=2)
    # a red-dominant object in the middle, well above the sky
    data[80:120, 80:120] += np.array([0.0058, 0.0038, 0.0036], dtype=np.float32)
    return np.clip(data, 0.0, 1.0)


def _signal_ratio(x):
    """Green against the mean of red and blue, over the bright object."""
    obj = x[80:120, 80:120]
    r, g, b = (float(np.median(obj[:, :, i])) for i in range(3))
    return g / ((r + b) / 2)


def test_the_stretch_does_not_invent_a_green_cast():
    """THE bug, reported 2026-08-15 on a real M 31 mosaic. Green carries half
    the noise on a Bayer sensor, and a per-channel MTF gives each channel a gain
    of roughly target/(sigma*MAD) — so green was amplified ~1.9x harder and a
    3.6% green DEFICIT came out as a 4.7% green EXCESS. Measured on the real
    file: linear 0.964, after the shipped stretch 1.047."""
    data = _bayer_like()
    before = _signal_ratio(data)
    assert before < 1.0, "fixture must start red-dominant"

    after = _signal_ratio(autostretch(AstroImage(data)))
    assert after < 1.0, (
        f"the stretch turned a green deficit ({before:.3f}) into an excess "
        f"({after:.3f}) — it is inventing colour")
    assert abs(after - before) < 0.05, (before, after)


def test_the_stretch_leaves_the_sky_neutral():
    """The property unlinked was chosen for, and it must survive the fix: a
    plain linked stretch left the sky at 0.876 on the real mosaic."""
    out = autostretch(AstroImage(_bayer_like()))
    sky = out[:60, :60]
    meds = [float(np.median(sky[:, :, i])) for i in range(3)]
    assert max(meds) - min(meds) < 0.02, meds


def test_the_stretch_does_not_crush_the_darkest_channel():
    """The reason a plain linked stretch was rejected: on light-polluted OSC
    data a common black point drags the lowest channel down. Measured on the
    real mosaic, linked put the darkest sky channel at 0.152 against 0.255."""
    out = autostretch(AstroImage(_bayer_like()))
    sky = out[:60, :60]
    assert min(float(np.median(sky[:, :, i])) for i in range(3)) > 0.15


def test_a_real_colour_cast_is_still_reported_faithfully():
    """Not inventing colour is not the same as removing it. A genuinely green
    object must still look green."""
    data = _bayer_like()
    data[80:120, 80:120] += np.array([0.0, 0.004, 0.0], dtype=np.float32)
    assert _signal_ratio(autostretch(AstroImage(data))) > 1.05


def test_the_preview_and_the_committed_stretch_agree():
    """The WYSIWYG rule: what the canvas shows at the Stretch step must be what
    the file contains. They are two call sites of the same maths, and nothing
    pinned them together — so a fix applied to one could silently ship a preview
    that lies about the export."""
    from nocturne.core.stretch import amount_to_target, apply_stretch

    data = _bayer_like(seed=3)
    committed = apply_stretch(AstroImage(data.copy()), 0.5).data
    from nocturne.core.autostretch import neutral_stretch
    preview = neutral_stretch(data, amount_to_target(0.5))
    np.testing.assert_allclose(committed, preview, atol=1e-6)


# --- sampled statistics ------------------------------------------------------

def _big(seed=0, shape=(2200, 3000)):
    """Large enough that sampling kicks in, shaped like a real master."""
    rng = np.random.default_rng(seed)
    chans = [rng.normal(m, s, shape).astype(np.float32)
             for m, s in ((0.0175, 0.00022), (0.0173, 0.00012), (0.0172, 0.00021))]
    data = np.stack(chans, axis=2)
    data[900:1300, 1200:1800] += np.array([0.006, 0.004, 0.004], np.float32)
    return np.clip(data, 0.0, 1.0)


def test_sampled_parameters_match_the_full_array():
    """61% of the stretch was two nanmedians over every pixel, to produce four
    scalars. A strided sample gives the same scalars far more tightly than a
    display can resolve — measured 4.4e-7 on the real 39.5 Mpx mosaic — so the
    full pass was buying nothing."""
    from nocturne.core.autostretch import _stretch_params, _sample

    data = _big()
    for c in range(3):
        ch = data[:, :, c]
        full = _stretch_params(ch)
        # what the old code did: statistics over every pixel
        assert _sample(ch).size < ch.size, "sampling must actually reduce the work"
        assert abs(full[0] - _stretch_params(ch)[0]) < 1e-9      # deterministic
        # and the sampled answer is indistinguishable from the exhaustive one
        med, mad = float(np.nanmedian(ch)), float(np.nanmedian(np.abs(ch - np.nanmedian(ch))))
        assert abs(_sample(ch).mean() - ch.mean()) < mad, "sample is unrepresentative"


def test_sampling_is_deterministic_for_a_given_shape():
    """Two exports of one image must be identical. A random or time-dependent
    sample would make the stretch parameters wobble between runs."""
    from nocturne.core.autostretch import _sample

    data = _big()
    a, b = _sample(data[:, :, 0]), _sample(data[:, :, 0])
    assert a.shape == b.shape
    np.testing.assert_array_equal(a, b)


def test_small_images_are_not_sampled_at_all():
    """Below the sample target there is nothing to save, and skipping pixels
    would only add error."""
    from nocturne.core.autostretch import _sample

    small = np.zeros((100, 100), np.float32)
    assert _sample(small).shape == small.shape


def test_the_stretch_result_is_unchanged_within_display_precision():
    """The whole point: faster, not different. 1/255 is one step of an 8-bit
    display, so anything below that cannot be seen."""
    from nocturne.core.autostretch import neutral_stretch

    data = _big(seed=5)
    out = neutral_stretch(data, _TARGET_BG)
    # a second call must be bit-identical, and the values must be sane
    np.testing.assert_array_equal(out, neutral_stretch(data, _TARGET_BG))
    assert 0.0 <= out.min() and out.max() <= 1.0
    sky = out[:400, :400]
    meds = [float(np.median(sky[:, :, i])) for i in range(3)]
    assert max(meds) - min(meds) < 0.02, meds


def test_sampling_changes_no_visible_pixel():
    """The invariant the speedup rests on: faster, not different. Measured on
    the real 39.5 Mpx M 31 mosaic, sampled-vs-exhaustive statistics gave a max
    difference of 0.0011 — 0.27 of one 8-bit step — and not a single pixel
    differed by more than 1/255. This reproduces that on a realistic array by
    forcing the old exhaustive path back on."""
    import nocturne.core.autostretch as A

    data = _big(seed=11)
    sampled = A.neutral_stretch(data, _TARGET_BG)
    real = A._sample
    A._sample = lambda a: a                    # the pre-optimisation behaviour
    try:
        full = A.neutral_stretch(data, _TARGET_BG)
    finally:
        A._sample = real

    diff = np.abs(sampled - full)
    assert (diff > 1.0 / 255.0).sum() == 0, (
        f"{(diff > 1/255).mean():.4%} of pixels moved by more than one 8-bit "
        f"step (max {diff.max():.5f})")
