import numpy as np
import pytest

from nocturne.core.color_balance import (MAX_SHIFT, Balance, apply_balance,
                                          single_tone, tone_weight)
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
    out = apply_balance(img, single_tone("midtones", blue=1.0, strength=0.0))
    assert np.array_equal(out.data, img.data)


def test_an_all_zero_mask_is_a_bit_exact_no_op():
    img = _grey()
    mask = np.zeros(img.data.shape[:2], np.float32)
    out = apply_balance(img, single_tone("midtones", blue=1.0), mask=mask)
    assert np.array_equal(out.data, img.data)


def test_pushing_blue_raises_the_blue_channel():
    img = _grey()
    out = apply_balance(img, single_tone("midtones", blue=1.0, preserve_lum=False)).data
    assert out[..., 2].mean() > img.data[..., 2].mean() + 0.01
    assert out[..., 0].mean() == pytest.approx(img.data[..., 0].mean(), abs=1e-6)


def test_the_three_axes_are_comparable_to_each_other():
    """One shared MAX_SHIFT, not one per channel: equal slider values must move
    equal amounts, or the axes cannot be reasoned about against each other."""
    img = _grey()
    moves = []
    for kw in ("red", "green", "blue"):
        out = apply_balance(img, single_tone("midtones", preserve_lum=False, **{kw: 1.0})).data
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
    out = apply_balance(img, Balance(midtones=(-1.0, 0.0, 1.0)), mask=mask).data
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
    out = apply_balance(img, Balance(midtones=(-1.0, 0.0, 1.0))).data
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
    out = apply_balance(img, single_tone("midtones", blue=1.0, preserve_lum=False)).data
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
    out = apply_balance(img, Balance(midtones=(-1.0, 0.0, 1.0)), mask=mask).data
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
        apply_balance(mono, single_tone("midtones", blue=1.0))


def test_preserves_is_linear_and_metadata():
    img = AstroImage(np.full((8, 8, 3), 0.5, np.float32), is_linear=False, metadata={"k": 1})
    out = apply_balance(img, single_tone("midtones", blue=0.5))
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_output_stays_in_range_and_float32():
    rng = np.random.default_rng(3)
    img = AstroImage(rng.random((16, 16, 3)).astype(np.float32), is_linear=False)
    out = apply_balance(img, single_tone("midtones", red=1.0, green=1.0, blue=1.0))
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def test_the_masked_path_matches_the_exhaustive_one_exactly():
    """apply_balance skips pixels the mask discards, because preserving
    luminosity converts to CIE Lab and back — 4.5 s of a 7.6 s Apply on the
    39.5 Mpx M 31 mosaic, for a mask selecting 2.11% of the frame.

    The optimisation must not change the answer, and this is the test that
    proves it. Measured agreement is 2.4e-7 — one float32 ULP, six hundred
    thousandths of one 8-bit level — not bit-for-bit, because converting a
    reshaped (N,1,3) slice to CIE Lab reassociates the arithmetic differently
    from converting an (H,W,3) image. That is floating point, not logic.

    It does not threaten WYSIWYG: preview and export both go through THIS
    function, so they agree with each other exactly. The comparison here is
    against an exhaustive implementation that no longer exists in the code.
    """
    from nocturne.core.color_balance import MAX_SHIFT, tone_weight
    from nocturne.core.narrowband import preserve_lightness

    from nocturne.core.color_balance import _SPARSE_MAX

    rng = np.random.default_rng(7)
    data = np.clip(_astro_like(64) + rng.normal(0, 0.02, (64, 64, 3)), 0, 1).astype(np.float32)
    img = AstroImage(data, is_linear=False)

    # A SPARSE mask, or this tests the wrong branch. The first version of this
    # test used a mask covering 78% of the frame, which takes the dense path —
    # so a mutation that dropped the mask weighting from the sparse path passed
    # it. Both branches are exercised below.
    mask = np.zeros((64, 64), np.float32)
    mask[:, 20:36] = np.linspace(0.0, 1.0, 16, dtype=np.float32)
    assert float((mask > 0).mean()) < _SPARSE_MAX, "this mask takes the dense path"
    assert (mask == 0).any() and (mask == 1).any(), "the mask must exercise both extremes"

    b = single_tone("midtones", red=-0.18, blue=0.20, preserve_lum=True, strength=0.8)
    fast = apply_balance(img, b, mask).data

    # the exhaustive reference, written out longhand
    w = tone_weight(data.mean(axis=2), "midtones")[..., None]
    shifted = np.clip(data + np.array(b.amounts("midtones"), np.float32) * MAX_SHIFT * w,
                      0.0, 1.0)
    shifted = preserve_lightness(shifted, data)
    slow = np.clip(data + (shifted - data) * mask[..., None] * b.strength, 0, 1).astype(np.float32)

    diff = float(np.max(np.abs(fast - slow)))
    assert diff < 1e-6, f"sparse path: max difference {diff:.3e} — larger than float32 noise"

    # and the DENSE branch, which the sparse gate hands off to above _SPARSE_MAX
    dense_mask = np.clip(np.tile(np.linspace(-0.2, 1.4, 64, dtype=np.float32), (64, 1)), 0, 1)
    assert float((dense_mask > 0).mean()) > _SPARSE_MAX, "this mask takes the sparse path"
    fast_d = apply_balance(img, b, dense_mask).data
    shifted_d = np.clip(data + np.array(b.amounts("midtones"), np.float32) * MAX_SHIFT * w,
                        0.0, 1.0)
    shifted_d = preserve_lightness(shifted_d, data)
    slow_d = np.clip(data + (shifted_d - data) * dense_mask[..., None] * b.strength,
                     0, 1).astype(np.float32)
    diff_d = float(np.max(np.abs(fast_d - slow_d)))
    assert diff_d < 1e-6, f"dense path: max difference {diff_d:.3e}"


def test_the_masked_path_leaves_discarded_pixels_bit_identical():
    """Where the mask is zero the pixel must be the ORIGINAL, byte for byte —
    not a value that merely rounds back to it."""
    data = _astro_like(48)
    img = AstroImage(data, is_linear=False)
    mask = np.zeros((48, 48), np.float32)
    mask[:24] = 1.0
    out = apply_balance(img, Balance(midtones=(-1.0, 0.0, 1.0)), mask).data
    assert np.array_equal(out[24:], data[24:])


# --- independent amounts per tonal range (2026-08-17) ------------------------

def test_the_tone_weights_partition_unity():
    """The property that makes stacking safe, and the reason MAX_SHIFT did NOT
    need recalibrating when three ranges became addressable at once: the three
    weights sum to exactly 1 at every luminance, so three full-travel ranges in
    the same direction move a channel by at most MAX_SHIFT — the same as one."""
    x = np.linspace(0.0, 1.0, 1001, dtype=np.float32)
    total = sum(tone_weight(x, t) for t in ("shadows", "midtones", "highlights"))
    assert np.max(np.abs(total - 1.0)) < 1e-5, f"max deviation {np.max(np.abs(total - 1.0))}"


def test_stacking_all_three_cannot_exceed_the_calibrated_maximum():
    """The consequence, measured on pixels rather than argued from the algebra.

    Bounded against MAX_SHIFT itself, not against what a single range happens to
    achieve on a given fixture: the midtone weight reaches 1.0 only at exactly
    luminance 0.5, which no pixel of a real image need land on, so comparing the
    two runs was comparing against an accident of the test data.
    """
    data = _astro_like(48)
    img = AstroImage(data, is_linear=False)
    three = apply_balance(img, Balance(shadows=(0, 0, 1.0), midtones=(0, 0, 1.0),
                                       highlights=(0, 0, 1.0),
                                       preserve_lum=False)).data
    moved = float(np.max(three[..., 2] - data[..., 2]))
    assert moved <= MAX_SHIFT + 1e-5, f"three ranges moved {moved}, past MAX_SHIFT"
    assert moved > MAX_SHIFT * 0.9, f"only moved {moved} — the stack is not reaching full travel"


def test_highlights_and_midtones_can_be_pushed_OPPOSITE_ways():
    """The limitation Andreas hit: "if I want to adjust highlights towards blue
    but adjust midtones towards red I simply cant do that". One adjustment, two
    ranges, opposite directions.

    The ramp stops at 0.85, not 1.0: at the very top a +blue shift has nowhere to
    go and clips, which reads as "highlights did not move" when the real cause is
    the ceiling. And the check is that each range's OWN colour dominates where
    that range peaks — not that the ranges are disjoint. They overlap on purpose;
    the three weights partition unity, so a smooth handover is the design.
    """
    n = 64
    ramp = np.tile(np.linspace(0.0, 0.85, n, dtype=np.float32), (n, 1))
    data = np.repeat(ramp[:, :, None], 3, axis=2)
    img = AstroImage(data, is_linear=False)
    out = apply_balance(img, Balance(midtones=(1.0, 0.0, 0.0),      # midtones -> red
                                     highlights=(0.0, 0.0, 1.0),   # highlights -> blue
                                     preserve_lum=False)).data

    row, base = out[0], data[0]
    mid = np.argmin(np.abs(ramp[0] - 0.5))       # where the midtone weight peaks
    top = n - 1                                   # where the highlight weight is largest

    assert row[mid][0] > base[mid][0] + 0.05, "midtones did not redden"
    assert row[mid][2] == pytest.approx(base[mid][2], abs=1e-4), (
        "the highlight blue reached the midtones, where its weight is zero")
    assert row[top][2] > base[top][2] + 0.02, "highlights did not blue"
    assert row[top][2] - base[top][2] > row[mid][2] - base[mid][2], (
        "blue is not concentrated in the highlights")


def test_one_range_alone_behaves_exactly_as_the_single_tone_version_did():
    """The migration guarantee. Everything saved before this change had exactly
    one range set, so it must produce byte-identical output — otherwise reopening
    an old project silently changes the picture."""
    data = _astro_like(48)
    img = AstroImage(data, is_linear=False)
    b = single_tone("midtones", red=-0.18, blue=0.20, preserve_lum=True, strength=0.8)
    got = apply_balance(img, b).data

    lum = data.mean(axis=2)
    w = tone_weight(lum, "midtones")[..., None]
    shifted = np.clip(data + np.array([-0.18, 0.0, 0.20], np.float32) * MAX_SHIFT * w, 0, 1)
    from nocturne.core.narrowband import preserve_lightness
    shifted = preserve_lightness(shifted, data)
    expect = np.clip(data + (shifted - data) * 0.8, 0, 1).astype(np.float32)
    assert np.array_equal(got, expect)


def test_a_balance_with_every_range_at_zero_is_still_a_no_op():
    data = _astro_like(32)
    img = AstroImage(data, is_linear=False)
    assert np.array_equal(apply_balance(img, Balance()).data, data)


def test_amounts_rejects_an_unknown_tone():
    with pytest.raises(ValueError):
        Balance().amounts("sideways")
    with pytest.raises(ValueError):
        single_tone("sideways", blue=1.0)


def test_describe_names_the_ranges_that_moved():
    """The log line and the provenance report both read this. When each range
    gained its own amounts the old single `tone` key vanished and BOTH surfaces
    silently fell back to nothing — no crash, no detail, no clue."""
    from nocturne.core.color_balance import describe
    assert describe({"midtones": [0, 0, 0.2]}) == "midtones"
    assert describe({"midtones": [0.1, 0, 0], "highlights": [0, 0, 0.3]}) == \
        "midtones, highlights"
    assert describe({"shadows": [0, 0, 0.2], "invert": True}) == "shadows (inverted)"
    assert describe({}) == "no change"
    assert describe({"midtones": [0.0, 0.0, 0.0]}) == "no change"
