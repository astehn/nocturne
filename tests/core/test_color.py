import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import ColorSettings, apply_color


def test_neutralize_background_equalizes_channel_medians():
    # green background raised -> a color cast
    data = np.full((32, 32, 3), 0.1, dtype=np.float32)
    data[..., 1] = 0.2  # green higher
    img = AstroImage(data)
    out = apply_color(img, ColorSettings(neutralize_background=True))
    meds = [float(np.median(out.data[..., c])) for c in range(3)]
    assert max(meds) - min(meds) < 1e-3


def test_neutralize_keeps_bg_neutral_and_preserves_nebula():
    # Red-dominant emission frame with a slightly-blue background (residual LP).
    # The fix must neutralize the sky WITHOUT desaturating the nebula or casting
    # the sky the complementary colour (the grey-world failure mode).
    rng = np.random.default_rng(0)
    H, W = 120, 120
    d = np.full((H, W, 3), 0.02, dtype=np.float32)
    d[..., 2] = 0.028                      # background slightly blue (LP residue)
    neb = np.zeros((H, W), dtype=bool)
    neb[:48, :] = True                     # ~40% of frame is red (Ha) nebula
    d[neb, 0] = 0.16; d[neb, 1] = 0.05; d[neb, 2] = 0.045
    d = np.clip(d + rng.normal(0, 0.002, d.shape).astype(np.float32), 0, 1)

    out = apply_color(AstroImage(d), ColorSettings(neutralize_background=True)).data
    bg = ~neb
    bgmed = [float(np.median(out[..., c][bg])) for c in range(3)]
    assert max(bgmed) - min(bgmed) < 0.005            # sky neutralized
    assert bgmed[2] <= bgmed[0] + 0.003               # sky NOT cast blue
    nebmed = [float(np.median(out[..., c][neb])) for c in range(3)]
    assert nebmed[0] > nebmed[1] and nebmed[0] > nebmed[2]  # nebula stays red


def test_mono_is_noop():
    img = AstroImage(np.full((8, 8), 0.3, dtype=np.float32))
    out = apply_color(img, ColorSettings())
    assert out.data.ndim == 2
    assert np.allclose(out.data, img.data)


def test_preserves_is_linear_and_dtype():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    out = apply_color(img, ColorSettings())
    assert out.is_linear is True
    assert out.data.dtype == np.float32
    assert out.data.max() <= 1.0 and out.data.min() >= 0.0


def test_remove_green_clamps_green_excess():
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = apply_color(AstroImage(data),
                      ColorSettings(neutralize_background=False, remove_green=True))
    assert out.data[..., 1].max() <= 0.3 + 1e-6  # clamped to (r+b)/2 = 0.3


def test_remove_green_function_clamps_green():
    from nocturne.core.color import remove_green
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = remove_green(AstroImage(data))
    assert out.data[..., 1].max() <= 0.3 + 1e-6           # clamped to (r+b)/2
    assert out.data[..., 0].max() <= 0.3 + 1e-6           # red untouched


def test_remove_green_leaves_non_green_pixel_untouched():
    from nocturne.core.color import remove_green
    data = np.zeros((2, 2, 3), dtype=np.float32)
    data[..., 0] = 0.5; data[..., 1] = 0.2; data[..., 2] = 0.5   # green already below avg
    out = remove_green(AstroImage(data))
    assert np.allclose(out.data[..., 1], 0.2)                     # unchanged


def test_remove_green_mono_is_noop():
    from nocturne.core.color import remove_green
    img = AstroImage(np.full((4, 4), 0.5, dtype=np.float32))
    out = remove_green(img)
    assert out.data.ndim == 2 and np.allclose(out.data, 0.5)


def test_remove_green_preserves_is_linear():
    from nocturne.core.color import remove_green
    img = AstroImage(np.full((4, 4, 3), 0.4, dtype=np.float32), is_linear=False)
    assert remove_green(img).is_linear is False


def test_remove_green_fringe_masked_degreens_inside_mask_only():
    from nocturne.core.color import remove_green_fringe_masked
    data = np.zeros((4, 4, 3), dtype=np.float32)
    data[..., 0] = 0.2; data[..., 1] = 0.8; data[..., 2] = 0.2   # strong green excess everywhere
    mask = np.zeros((4, 4), dtype=np.float32)
    mask[0, 0] = 1.0                                             # only this pixel is "near a star"
    out = remove_green_fringe_masked(AstroImage(data), mask, 1.0)
    assert out.data[0, 0, 1] < 0.3                              # masked pixel de-greened to ~avg(R,B)
    assert np.allclose(out.data[1, 1, 1], 0.8)                  # unmasked pixel untouched


def test_remove_green_fringe_masked_strength_zero_and_empty_mask_are_identity():
    from nocturne.core.color import remove_green_fringe_masked
    data = np.random.default_rng(1).random((4, 4, 3)).astype(np.float32)
    mask = np.ones((4, 4), dtype=np.float32)
    assert np.allclose(remove_green_fringe_masked(AstroImage(data), mask, 0.0).data, data)
    assert np.allclose(
        remove_green_fringe_masked(AstroImage(data), np.zeros((4, 4), np.float32), 1.0).data, data)


def test_remove_green_fringe_masked_mono_is_noop():
    from nocturne.core.color import remove_green_fringe_masked
    img = AstroImage(np.full((4, 4), 0.5, dtype=np.float32))
    out = remove_green_fringe_masked(img, np.ones((4, 4), np.float32), 1.0)
    assert out.data.ndim == 2 and np.allclose(out.data, 0.5)

# ---------------------------------------------------------------- tint gains

def test_zero_tint_leaves_the_image_untouched():
    """The default must be a true no-op, not merely 'close'.

    Assert-UNCHANGED rather than assert-not-wrong: a gain triple that is nearly
    but not exactly 1.0 would still pass a tolerance check while quietly
    recolouring every image that never touches the sliders.
    """
    from nocturne.core.color import tint_gains
    r, g, b = tint_gains(0.0, 0.0)
    assert (r, g, b) == (1.0, 1.0, 1.0)


def test_negative_tint_moves_toward_green_positive_toward_magenta():
    from nocturne.core.color import tint_gains
    gr, gg, gb = tint_gains(-1.0, 0.0)
    assert gg > 1.0 and gr < 1.0 and gb < 1.0, "negative tint must raise green"
    mr, mg, mb = tint_gains(1.0, 0.0)
    assert mg < 1.0 and mr > 1.0 and mb > 1.0, "positive tint must raise red+blue"


def test_positive_temperature_warms_negative_cools():
    from nocturne.core.color import tint_gains
    wr, _wg, wb = tint_gains(0.0, 1.0)
    assert wr > 1.0 and wb < 1.0, "warm must raise red and lower blue"
    cr, _cg, cb = tint_gains(0.0, -1.0)
    assert cr < 1.0 and cb > 1.0, "cool must lower red and raise blue"


def test_gains_are_exposure_neutral():
    """A colour control must not change brightness.

    Without this the sliders double as an exposure control and the user cannot
    tell which one they are actually operating.
    """
    import numpy as np
    from nocturne.core.color import tint_gains, _LUM_WEIGHTS
    for t in (-1.0, -0.4, 0.0, 0.6, 1.0):
        for w in (-1.0, 0.0, 1.0):
            g = np.asarray(tint_gains(t, w), dtype=np.float64)
            assert abs(float((g * _LUM_WEIGHTS).sum()) - 1.0) < 1e-6, (t, w)


def test_tint_preserves_the_colour_DIFFERENCES_between_stars():
    """THE test for this feature. It encodes the requirement, not the mechanism.

    Andreas asked for this because his stacks carry a magenta cast; a mirrored
    SCNR was rejected because a CLAMP removes the colour difference between an
    orange star and a blue one at the same time as it removes the cast.

    The invariant a multiplicative gain actually guarantees is that R/G is
    scaled by the SAME factor for every star, so the ratio between any two
    stars' R/G is untouched. (Chromaticity — each star normalised by its own
    sum — is NOT preserved, because that normalisation is non-linear; an earlier
    version of this test asserted that and was simply wrong.)

    A clamp fails this: whether a given star is clamped depends on its own
    values, so it moves stars by different amounts. Verified by mutation.
    """
    import numpy as np
    from nocturne.core.color import apply_tint
    from nocturne.core.image import AstroImage

    stars = np.array([[[0.60, 0.30, 0.20],      # orange
                       [0.20, 0.30, 0.60],      # blue
                       [0.40, 0.40, 0.40],      # neutral
                       [0.15, 0.45, 0.25]]], dtype=np.float32)   # green-ish
    img = AstroImage(stars.copy(), is_linear=True, metadata={})
    out = apply_tint(img, -1.0, 0.3).data

    def ratios(a):
        return np.stack([a[0, :, 0] / a[0, :, 1], a[0, :, 2] / a[0, :, 1]], axis=1)

    before, after = ratios(stars), ratios(out)
    for i in range(stars.shape[1]):
        for j in range(i + 1, stars.shape[1]):
            b = before[i] / before[j]
            a = after[i] / after[j]
            assert np.allclose(b, a, rtol=1e-4), (
                f"stars {i},{j} moved by different amounts: {b} -> {a}; "
                "a gain must shift every star identically"
            )


def test_apply_tint_at_zero_returns_the_data_unchanged():
    import numpy as np
    from nocturne.core.color import apply_tint
    from nocturne.core.image import AstroImage
    rng = np.random.default_rng(0)
    data = rng.random((8, 8, 3)).astype(np.float32)
    out = apply_tint(AstroImage(data.copy(), is_linear=True, metadata={}), 0.0, 0.0)
    assert np.array_equal(out.data, data), "zero tint must be bit-identical"


def test_color_settings_carry_tint_through_apply_color():
    import numpy as np
    from nocturne.core.color import ColorSettings, apply_color
    from nocturne.core.image import AstroImage
    rng = np.random.default_rng(1)
    data = (rng.random((16, 16, 3)) * 0.3 + 0.1).astype(np.float32)
    img = AstroImage(data, is_linear=True, metadata={})
    plain = apply_color(img, ColorSettings(neutralize_background=False))
    tinted = apply_color(img, ColorSettings(neutralize_background=False, tint=-1.0))
    g_plain = float(np.median(plain.data[..., 1] / np.maximum(plain.data.mean(axis=2), 1e-6)))
    g_tint = float(np.median(tinted.data[..., 1] / np.maximum(tinted.data.mean(axis=2), 1e-6)))
    assert g_tint > g_plain, "tint must reach the image through apply_color"
