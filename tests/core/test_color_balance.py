import numpy as np
import pytest

from nocturne.core.color_balance import Balance, apply_balance, tone_weight
from nocturne.core.image import AstroImage


def _grey(v=0.5, h=32, w=32):
    return AstroImage(np.full((h, w, 3), v, np.float32), is_linear=False)


def test_zero_sliders_are_a_bit_exact_no_op():
    """Opening the tool and closing it must not alter a single pixel."""
    img = _grey()
    out = apply_balance(img, Balance())
    assert np.array_equal(out.data, img.data)


def test_zero_strength_is_a_bit_exact_no_op():
    img = _grey()
    out = apply_balance(img, Balance(blue=1.0, strength=0.0))
    assert np.array_equal(out.data, img.data)


def test_an_all_zero_mask_is_a_bit_exact_no_op():
    img = _grey()
    mask = np.zeros(img.data.shape[:2], np.float32)
    out = apply_balance(img, Balance(blue=1.0), mask=mask)
    assert np.array_equal(out.data, img.data)


def test_pushing_blue_raises_the_blue_channel():
    img = _grey()
    out = apply_balance(img, Balance(blue=1.0, preserve_lum=False)).data
    assert out[..., 2].mean() > img.data[..., 2].mean() + 0.01
    assert out[..., 0].mean() == pytest.approx(img.data[..., 0].mean(), abs=1e-6)


def test_the_three_axes_are_comparable_to_each_other():
    """One shared MAX_SHIFT, not one per channel: equal slider values must move
    equal amounts, or the axes cannot be reasoned about against each other."""
    img = _grey()
    moves = []
    for kw in ("red", "green", "blue"):
        out = apply_balance(img, Balance(preserve_lum=False, **{kw: 1.0})).data
        ch = {"red": 0, "green": 1, "blue": 2}[kw]
        moves.append(float(out[..., ch].mean() - img.data[..., ch].mean()))
    assert max(moves) - min(moves) < 1e-6, f"axes move unequally: {moves}"


def test_outside_the_mask_the_pixels_are_UNCHANGED():
    """Captured before and compared after, not compared against a wrong value.
    `assert x != wrong` passes while the code writes a DIFFERENT wrong value —
    that exact weakness got through twice on one branch."""
    img = _grey()
    before = img.data.copy()
    mask = np.zeros(img.data.shape[:2], np.float32)
    mask[:16] = 1.0                                  # only the top half is selected
    out = apply_balance(img, Balance(blue=1.0, red=-1.0), mask=mask).data
    assert np.array_equal(out[16:], before[16:]), "the unmasked half moved"
    assert not np.array_equal(out[:16], before[:16]), "the masked half did not move"


def _astro_like(n=48):
    """A soft object on dark sky with a mild warm cast — the kind of picture this
    tool is pointed at, and crucially nowhere near the sRGB gamut boundary."""
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / n
    r = np.hypot(y - 0.5, x - 0.5) * 2.0
    lum = np.clip(0.85 * np.exp(-3.0 * r * r) + 0.05, 0.0, 1.0)
    return np.clip(np.stack([lum * 1.05, lum, lum * 0.92], -1), 0, 1).astype(np.float32)


def test_preserve_luminosity_holds_lightness_while_the_colour_moves():
    """Both halves, or the test passes vacuously: an implementation that did
    nothing at all would hold L* perfectly.

    On real-shaped data the lightness is held EXACTLY — measured max drift 0.000
    L* at a full-travel shift, because the L* round trip is exact whenever the
    colour stays in gamut. It is only uniform-random RGB, which sits on the
    gamut boundary constantly, that drifts (2.26 L* at full travel, 0.34 at the
    settings Andreas actually uses) — and that is sRGB clipping, not this code.
    """
    from skimage.color import rgb2lab
    img = AstroImage(_astro_like(), is_linear=False)
    out = apply_balance(img, Balance(blue=1.0, red=-1.0, preserve_lum=True)).data
    lab_before = rgb2lab(np.clip(img.data, 0, 1))
    lab_after = rgb2lab(np.clip(out, 0, 1))
    assert np.max(np.abs(lab_after[..., 0] - lab_before[..., 0])) < 0.5, "L* drifted"
    ab_move = np.max(np.abs(lab_after[..., 1:] - lab_before[..., 1:]))
    assert ab_move > 1.0, f"the colour never moved ({ab_move:.3f}) — vacuous pass"


def test_without_preserve_luminosity_the_lightness_is_free_to_move():
    """The complementary case — otherwise the checkbox could do nothing at all
    and the test above would still pass."""
    from skimage.color import rgb2lab
    img = _grey()
    out = apply_balance(img, Balance(blue=1.0, preserve_lum=False)).data
    l_before = rgb2lab(np.clip(img.data, 0, 1))[..., 0]
    l_after = rgb2lab(np.clip(out, 0, 1))[..., 0]
    assert np.max(np.abs(l_after - l_before)) > 0.5


def test_preserve_luminosity_survives_a_feathered_mask():
    """Guards the MASKED path: preservation must still hold where the mask is
    between 0 and 1, not only where it is 1.

    This started life as a test that preserving L* before the blend differs from
    after. It does not — measured on real-shaped data the two orders differ by
    0.01 of one 8-bit level, and the design's claim of a halo across the feather
    was simply wrong. The order kept in the code matches Photoshop's layer
    model; it is not numerically load-bearing."""
    from skimage.color import rgb2lab
    img = _grey(0.5, 32, 32)
    mask = np.tile(np.linspace(0.0, 1.0, 32, dtype=np.float32), (32, 1))   # a ramp
    out = apply_balance(img, Balance(blue=1.0, red=-1.0, preserve_lum=True), mask=mask).data
    l_before = rgb2lab(np.clip(img.data, 0, 1))[..., 0]
    l_after = rgb2lab(np.clip(out, 0, 1))[..., 0]
    assert np.max(np.abs(l_after - l_before)) < 1.0, "L* drifted across the feather"


def test_midtones_acts_on_midtones_and_leaves_the_extremes():
    lum = np.linspace(0.0, 1.0, 101, dtype=np.float32)
    w = tone_weight(lum, "midtones")
    assert w[50] > 0.9 and w[0] < 0.05 and w[-1] < 0.05


def test_shadows_and_highlights_act_at_their_own_ends():
    lum = np.linspace(0.0, 1.0, 101, dtype=np.float32)
    s, h = tone_weight(lum, "shadows"), tone_weight(lum, "highlights")
    assert s[0] > 0.9 and s[-1] < 0.05
    assert h[-1] > 0.9 and h[0] < 0.05


def test_tone_weight_rejects_an_unknown_tone():
    with pytest.raises(ValueError):
        tone_weight(np.zeros(4, np.float32), "sideways")


def test_a_mono_image_is_rejected_rather_than_silently_ignored():
    mono = AstroImage(np.full((8, 8), 0.5, np.float32), is_linear=False)
    with pytest.raises(ValueError):
        apply_balance(mono, Balance(blue=1.0))


def test_preserves_is_linear_and_metadata():
    img = AstroImage(np.full((8, 8, 3), 0.5, np.float32), is_linear=False, metadata={"k": 1})
    out = apply_balance(img, Balance(blue=0.5))
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_output_stays_in_range_and_float32():
    rng = np.random.default_rng(3)
    img = AstroImage(rng.random((16, 16, 3)).astype(np.float32), is_linear=False)
    out = apply_balance(img, Balance(red=1.0, green=1.0, blue=1.0))
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
