import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.enhance import boost_hue, darken_sky, lighten_sky, soft_glow, vibrance, star_colour_layers, dark_structure
from skimage.color import rgb2hsv


def _rgb(pixels):
    return AstroImage(np.array([pixels], dtype=np.float32), is_linear=False)


def test_boost_hue_is_selective():
    # a red pixel and a teal pixel side by side; Boost Red raises red saturation, not teal
    from skimage.color import rgb2hsv
    img = _rgb([(0.6, 0.2, 0.2), (0.2, 0.6, 0.6)])   # red-ish, teal-ish
    out = boost_hue(img, 0.0).data                    # hue 0 = red
    before = rgb2hsv(np.clip(img.data, 0, 1))
    after = rgb2hsv(np.clip(out, 0, 1))
    assert after[0, 0, 1] > before[0, 0, 1] + 0.01    # red pixel more saturated
    assert abs(after[0, 1, 1] - before[0, 1, 1]) < 0.01   # teal pixel ~unchanged


def test_boost_cyan_and_blue_target_their_hues():
    from skimage.color import rgb2hsv
    teal = _rgb([(0.2, 0.6, 0.6)])
    assert rgb2hsv(boost_hue(teal, 0.5).data)[0, 0, 1] > rgb2hsv(teal.data)[0, 0, 1] + 0.01
    blue = _rgb([(0.2, 0.2, 0.6)])
    assert rgb2hsv(boost_hue(blue, 0.667).data)[0, 0, 1] > rgb2hsv(blue.data)[0, 0, 1] + 0.01


def test_darken_sky_lowers_background_keeps_bright():
    img = _rgb([(0.10, 0.10, 0.10), (0.80, 0.80, 0.80)])   # dark bg, bright
    out = darken_sky(img).data
    assert out[0, 0].mean() < 0.10                          # background pulled down
    assert abs(out[0, 1].mean() - 0.80) < 0.005             # bright untouched
    assert out.min() >= 0.0


def test_lighten_sky_raises_background_keeps_bright():
    img = _rgb([(0.10, 0.10, 0.10), (0.80, 0.80, 0.80)])
    out = lighten_sky(img).data
    assert out[0, 0].mean() > 0.10                          # background lifted
    assert abs(out[0, 1].mean() - 0.80) < 0.01
    assert out.max() <= 1.0


def test_boost_hue_mono_passthrough():
    mono = AstroImage(np.full((4, 4), 0.3, np.float32), is_linear=False)
    assert boost_hue(mono, 0.0).data.ndim == 2


def test_sky_ops_handle_mono():
    mono = AstroImage(np.full((4, 4), 0.1, np.float32), is_linear=False)
    assert darken_sky(mono).data.ndim == 2 and darken_sky(mono).data.max() < 0.1
    assert lighten_sky(mono).data.ndim == 2 and lighten_sky(mono).data.max() > 0.1


def test_soft_glow_blooms_around_highlights():
    data = np.zeros((20, 20, 3), np.float32)
    data[8:12, 8:12] = 0.7                                   # bright central blob
    out = soft_glow(AstroImage(data, is_linear=False), amount=0.4, radius=3.0, threshold=0.2).data
    assert out[9, 9].mean() > data[9, 9].mean()             # blob brightens
    assert out[7, 9].mean() > 0.004                         # glow bleeds OUTSIDE the blob edge (was pure black)
    assert out[7, 9].mean() > out[5, 9].mean()              # ...and decays with distance (a real bloom)
    assert out[0, 0].mean() < 0.03                          # far corner still dark


def test_soft_glow_works_on_mono():
    data = np.zeros((16, 16), np.float32)
    data[6:10, 6:10] = 0.8
    out = soft_glow(AstroImage(data, is_linear=False), amount=0.5, radius=3.0, threshold=0.3).data
    assert out[7, 7] > 0.8                                   # mono glows too (not a passthrough)


def test_vibrance_lifts_unsaturated_more_than_saturated():
    data = np.array([[[0.6, 0.55, 0.5], [0.9, 0.2, 0.2]]], np.float32)   # low-sat, high-sat (both bright)
    out = vibrance(AstroImage(data, is_linear=False), amount=0.5).data
    s_in, s_out = rgb2hsv(data)[..., 1], rgb2hsv(np.clip(out, 0, 1))[..., 1]
    assert s_out[0, 0] - s_in[0, 0] > 0                      # low-sat pixel gained saturation
    assert (s_out[0, 0] - s_in[0, 0]) > (s_out[0, 1] - s_in[0, 1])   # more than the saturated one


def test_vibrance_protects_shadows_and_mono():
    dark = np.array([[[0.05, 0.03, 0.03]]], np.float32)      # below shadow-protect knee
    out = vibrance(AstroImage(dark, is_linear=False), amount=0.5).data
    assert np.allclose(out, dark, atol=1e-3)                 # background protected
    mono = AstroImage(np.full((4, 4), 0.3, np.float32), is_linear=False)
    assert np.allclose(vibrance(mono).data, mono.data)       # mono unchanged


def test_enhance_ops_registry_matches_enhance_names():
    # Every recipe-captured tap except Star Colour (which needs a star split and
    # is special-cased by callers) must have a replay function in ENHANCE_OPS —
    # otherwise batch replay of that tap KeyErrors at runtime. Drift-guard: if a
    # future tap is added to ENHANCE_NAMES but forgotten in ENHANCE_OPS, this
    # fails structurally instead of only at batch time.
    from nocturne.ui.pipeline import ENHANCE_NAMES
    from nocturne.core.enhance import ENHANCE_OPS
    assert set(ENHANCE_NAMES) - {"Star Colour"} == set(ENHANCE_OPS)


def _plain_recombine(base_val, stars):
    return 1.0 - (1.0 - base_val) * (1.0 - stars)


def test_star_colour_layers_colours_only_stars():
    # starless nebula (uniform dim) + a stars layer that is black except one
    # faint-gold star. Boosting must colour the star and leave nebula untouched.
    starless = AstroImage(np.full((8, 8, 3), 0.2, np.float32), is_linear=False)
    stars = np.zeros((8, 8, 3), np.float32); stars[4, 4] = (0.30, 0.24, 0.18)  # low-sat gold
    out = star_colour_layers(starless, AstroImage(stars, is_linear=False), amount=0.6).data
    plain = _plain_recombine(0.2, stars)
    s_out = rgb2hsv(np.clip(out, 0, 1))[..., 1]
    s_plain = rgb2hsv(np.clip(plain, 0, 1))[..., 1]
    assert s_out[4, 4] > s_plain[4, 4] + 0.02              # star gains saturation vs plain recombine
    assert np.allclose(out[0, 0], plain[0, 0], atol=1e-4)  # off-star pixel: identical to plain recombine


def test_star_colour_layers_zero_amount_and_mono():
    starless = AstroImage(np.full((6, 6, 3), 0.15, np.float32), is_linear=False)
    stars = np.zeros((6, 6, 3), np.float32); stars[3, 3] = (0.4, 0.3, 0.2)
    out0 = star_colour_layers(starless, AstroImage(stars, is_linear=False), amount=0.0).data
    assert np.allclose(out0, _plain_recombine(0.15, stars), atol=1e-5)   # amount 0 = plain recombine
    mono_less = AstroImage(np.full((6, 6), 0.15, np.float32), is_linear=False)
    mono_st = np.zeros((6, 6), np.float32); mono_st[3, 3] = 0.5
    out_m = star_colour_layers(mono_less, AstroImage(mono_st, is_linear=False), amount=0.6).data
    assert np.allclose(out_m, _plain_recombine(0.15, mono_st), atol=1e-5)  # mono: no chroma, unchanged


def test_vibrance_does_not_tint_true_neutral():
    grey = np.full((1, 1, 3), 0.6, np.float32)      # bright r=g=b neutral
    out = vibrance(AstroImage(grey, is_linear=False), amount=0.5).data
    assert np.allclose(out, grey, atol=2e-3)         # stays neutral — no red cast


def test_soft_glow_threshold_one_is_finite():
    data = np.ones((4, 4, 3), np.float32)            # lum == 1 everywhere -> b-a == 0 in smoothstep
    out = soft_glow(AstroImage(data, is_linear=False), threshold=1.0).data
    assert np.isfinite(out).all()                    # no divide-by-zero NaN


def test_dark_structure_deepens_dark_lane():
    # mid-brightness field with a darker lane through the middle
    data = np.full((32, 32, 3), 0.45, np.float32)
    data[14:18, :] = 0.28                                   # a dark dust lane
    img = AstroImage(data, is_linear=False)
    out = dark_structure(img, amount=0.6, radius=6.0).data
    assert out[16, 16].mean() < data[16, 16].mean() - 0.005   # lane gets darker (more contrast)
    assert out[16, 16].mean() < out[2, 2].mean()              # lane darker than the surrounding field


def test_dark_structure_protects_background_and_bright():
    data = np.full((16, 16, 3), 0.02, np.float32)          # pure faint background (noise floor)
    data[8, 8] = 0.9                                        # a bright point
    out = dark_structure(AstroImage(data, is_linear=False), amount=0.6).data
    assert abs(out[0, 0].mean() - 0.02) < 5e-3             # background ~untouched (no noise crunch)
    assert abs(out[8, 8].mean() - 0.9) < 5e-3             # bright signal ~untouched


def test_dark_structure_zero_amount_and_mono():
    data = np.full((16, 16, 3), 0.4, np.float32); data[8, 8] = 0.2
    assert np.allclose(dark_structure(AstroImage(data, is_linear=False), amount=0.0).data, data, atol=1e-5)
    mono = np.full((16, 16), 0.4, np.float32); mono[8, 8] = 0.2
    out = dark_structure(AstroImage(mono, is_linear=False), amount=0.6).data   # mono supported, no crash
    assert out.shape == mono.shape


def test_dark_structure_is_brightness_neutral():
    # A symmetric local-contrast pass must not net-darken (net-darkening was the
    # old muddy/washed behaviour): the frame mean stays ~unchanged while local
    # contrast in the dark band rises.
    rng = np.random.RandomState(0)
    yy, xx = np.mgrid[0:64, 0:64]
    lum = (0.20 + 0.08 * np.sin(xx / 6.0) * np.cos(yy / 5.0)).astype(np.float32)   # dusty mid-dark texture
    data = np.stack([lum] * 3, axis=2)
    out = dark_structure(AstroImage(data, is_linear=False), amount=0.5, radius=8.0).data
    assert abs(out.mean() - data.mean()) < 2e-3                       # brightness-neutral (no muddy darkening)
    from scipy.ndimage import gaussian_filter
    hp_in = lum - gaussian_filter(lum, 8.0)
    hp_out = out[..., 0] - gaussian_filter(out[..., 0], 8.0)
    assert hp_out.std() > hp_in.std()                                # local contrast increased (definition)


# --- Sharpen Nebulosity -------------------------------------------------------

def _neb_field(sky_frac=0.3, seed=1):
    """Nebulosity with real fine structure over a faint noisy sky."""
    from scipy.ndimage import gaussian_filter
    rng = np.random.default_rng(seed)
    f = gaussian_filter(rng.normal(0, 1, (200, 200)), 2.0)
    f = (f - f.min()) / (f.max() - f.min())
    a = np.repeat((0.30 + 0.35 * f)[..., None], 3, 2).astype(np.float32)
    n = int(200 * sky_frac)
    a[:n] = 0.02 + rng.normal(0, 0.006, (n, 200, 3))
    return AstroImage(np.clip(a, 0, 1).astype(np.float32), is_linear=False), n


def _acut(arr, sl):
    g = arr[sl].mean(axis=2)
    return float(np.abs(np.diff(g, axis=1)).mean())


def test_sharpen_lifts_nebulosity_detail_and_leaves_the_sky_alone():
    """An unsharp mask on a stretched astro frame finds the noise first — the
    signal mask is what stops that, and it is the reason this is safe."""
    from nocturne.core.enhance import sharpen_nebulosity_layers
    sl, n = _neb_field()
    stars = AstroImage(np.zeros((200, 200, 3), np.float32), is_linear=False)
    base = sharpen_nebulosity_layers(sl, stars, amount=0.0)
    out = sharpen_nebulosity_layers(sl, stars)

    neb = _acut(out.data, np.s_[100:]) / _acut(base.data, np.s_[100:])
    sky = _acut(out.data, np.s_[:n - 5]) / _acut(base.data, np.s_[:n - 5])
    assert neb > 1.08, f"nebulosity barely sharpened (x{neb:.3f})"
    assert sky < 1.02, f"faint sky was sharpened too (x{sky:.3f}) — the mask leaked"


def test_the_effect_does_not_depend_on_how_much_sky_is_in_frame():
    """The original floor_pct=40 anchored the ramp to the middle of the
    histogram, so a wide field pushed it up INTO the signal and the mask over
    nebulosity swung from 0.08 to 1.00 — a 4x difference in effect between
    targets, for no reason the user could see."""
    from nocturne.core.enhance import sharpen_nebulosity_layers
    stars = AstroImage(np.zeros((200, 200, 3), np.float32), is_linear=False)
    gains = []
    for frac in (0.10, 0.30, 0.60, 0.80):
        sl, n = _neb_field(frac)
        base = sharpen_nebulosity_layers(sl, stars, amount=0.0)
        out = sharpen_nebulosity_layers(sl, stars)
        gains.append(_acut(out.data, np.s_[n + 20:]) / _acut(base.data, np.s_[n + 20:]))
    spread = max(gains) / min(gains)
    # Measured, not guessed: the tuned values give 1.009 across 10-80% sky, the
    # old floor_pct=40/ramp=0.25 gives 1.095. 1.05 separates them cleanly — an
    # earlier threshold of 1.15 sat exactly on the old spread and let it pass.
    assert spread < 1.05, f"effect varies {spread:.3f}x with sky fraction: {gains}"


def test_the_stars_layer_is_never_sharpened():
    """The whole premise. Stars are split out, sharpened never touches them, and
    they are screened back — so they cannot ring."""
    from nocturne.core.enhance import sharpen_nebulosity_layers
    sl, _ = _neb_field()
    star_arr = np.zeros((200, 200, 3), np.float32)
    star_arr[120, 120] = 0.95
    stars = AstroImage(star_arr, is_linear=False)
    flat = AstroImage(np.full((200, 200, 3), 0.3, np.float32), is_linear=False)

    # against a perfectly flat starless there is no detail to add, so any change
    # at the star could only have come from sharpening the star itself
    a = sharpen_nebulosity_layers(flat, stars, amount=0.0)
    b = sharpen_nebulosity_layers(flat, stars, amount=1.0)
    assert np.allclose(a.data, b.data, atol=1e-6), "the stars layer was altered"

    # ...and the star must arrive at full strength, not merely at the SAME
    # strength in both. Comparing the two runs alone is blind to anything that
    # dims the star layer, because it dims both sides equally.
    expect = 1.0 - (1.0 - flat.data) * (1.0 - star_arr)
    assert np.allclose(b.data, expect, atol=1e-6), "the star did not survive intact"


def test_amount_zero_is_a_plain_recombine():
    from nocturne.core.enhance import sharpen_nebulosity_layers
    sl, _ = _neb_field()
    stars = AstroImage(np.zeros((200, 200, 3), np.float32), is_linear=False)
    out = sharpen_nebulosity_layers(sl, stars, amount=0.0)
    assert np.allclose(out.data, sl.data, atol=1e-6)


def test_taps_stack_gently_rather_than_all_at_once():
    """Enhancements are tap-to-stack, which is what keeps this from being the
    most abusable control in the app: each tap is small, and more is a choice."""
    from nocturne.core.enhance import sharpen_nebulosity_layers
    sl, _ = _neb_field()
    stars = AstroImage(np.zeros((200, 200, 3), np.float32), is_linear=False)
    base = sharpen_nebulosity_layers(sl, stars, amount=0.0)
    gains, cur = [], sl
    for _ in range(3):
        cur = sharpen_nebulosity_layers(cur, stars)
        gains.append(_acut(cur.data, np.s_[100:]) / _acut(base.data, np.s_[100:]))
    assert gains == sorted(gains), gains
    assert gains[0] < 1.25, f"a single tap is too strong ({gains[0]:.3f})"
    assert gains[2] > gains[0] * 1.2, "stacking taps must actually accumulate"
