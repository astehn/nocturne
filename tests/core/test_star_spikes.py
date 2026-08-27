import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.star_spikes import Star, detect_stars, add_spikes


def _blob(h=64, w=64, cy=20, cx=40, amp=0.9, sigma=2.0):
    yy, xx = np.mgrid[0:h, 0:w]
    g = amp * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma ** 2)))
    rng = np.random.default_rng(0)
    lum = np.clip(g + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    return np.repeat(lum[:, :, None], 3, axis=2)


def test_detect_finds_bright_star():
    stars = detect_stars(_blob(cy=20, cx=40))
    assert len(stars) >= 1
    s = stars[0]                       # brightest first
    assert abs(s.x - 40) <= 2 and abs(s.y - 20) <= 2   # x=col, y=row
    assert len(s.color) == 3


def test_detect_empty_on_flat():
    assert detect_stars(np.zeros((32, 32, 3), np.float32)) == []


def _one_star(flux=1.0, color=(1.0, 1.0, 1.0), cy=32, cx=32):
    return [Star(x=float(cx), y=float(cy), flux=flux, color=color)]


def _dark(h=64, w=64):
    return AstroImage(np.zeros((h, w, 3), np.float32), is_linear=False)


def test_length_zero_is_noop():
    img = _dark()
    out = add_spikes(img, _one_star(), 0.0, 6, 0.0).data
    assert np.allclose(out, img.data)


def test_count_zero_is_noop():
    img = _dark()
    assert np.allclose(add_spikes(img, _one_star(), 0.5, 0, 0.0).data, img.data)


def test_spikes_brighten_the_four_arms():
    out = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0).data
    assert out[32, 34].max() > 0.05        # on the horizontal arm (2 px out)
    assert out[34, 32].max() > 0.05        # on the vertical arm
    assert out[44, 44].max() < 0.02        # far off any arm -> untouched


def test_intensity_scales_spike_brightness():
    # A lower intensity makes the same spikes fainter everywhere they draw.
    full = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0, 1.0).data
    half = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0, 0.5).data
    for px in ((32, 32), (32, 34), (34, 32)):        # core + both arms
        assert 0.0 < half[px].max() < full[px].max()


def test_intensity_default_is_full_strength():
    # Omitting intensity must reproduce the previous (full-strength) look exactly.
    default = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0).data
    explicit = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0, 1.0).data
    assert np.allclose(default, explicit)


def test_intensity_zero_is_noop():
    img = _dark()
    assert np.allclose(add_spikes(img, _one_star(), 1.0, 6, 0.0, 0.0).data, img.data)


def test_core_has_a_bloom_glow():
    # The star core carries a soft bloom so spikes emanate from a glow, not a dot.
    out = add_spikes(_dark(), _one_star(), 1.0, 1, 0.0).data
    assert out[32, 32].max() > 0.3         # bright bloomed core
    assert out[33, 33].max() > 0.1         # glow bleeds a little off-axis near the core


def test_brighter_star_gets_longer_arm():
    # Arm length normalizes to the brightest star in the SAME call, so both
    # stars must be passed together to compare their relative extents.
    bright = Star(x=48.0, y=16.0, flux=1.0, color=(1.0, 1.0, 1.0))
    faint = Star(x=16.0, y=48.0, flux=0.3, color=(1.0, 1.0, 1.0))
    out = add_spikes(_dark(), [bright, faint], 1.0, 2, 0.0).data

    def extent(cx, cy):   # furthest lit pixel along the rightward horizontal arm
        lit = np.where(out[cy, cx:].max(axis=1) > 0.02)[0]
        return int(lit.max()) if len(lit) else 0

    assert extent(48, 16) > extent(16, 48)     # brighter star -> longer arm


def test_rotation_puts_spikes_on_the_diagonal():
    out = add_spikes(_dark(), _one_star(), 1.0, 1, 45.0).data
    assert out[34, 34].max() > 0.05        # diagonal arm now lit
    assert out[32, 40].max() < 0.02        # beyond the original horizontal axis: dark


def test_star_colour_tints_its_spikes():
    out = add_spikes(_dark(), _one_star(color=(1.0, 0.0, 0.0)), 1.0, 1, 0.0).data
    px = out[32, 34]
    assert px[0] > px[1] and px[0] > px[2]     # red spike


def test_output_range_dtype_and_metadata():
    img = AstroImage(np.full((48, 48, 3), 0.2, np.float32),
                     is_linear=False, metadata={"k": 1})
    out = add_spikes(img, _one_star(cy=24, cx=24), 0.8, 3, 30.0)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_greyscale_path():
    img = AstroImage(np.zeros((48, 48), np.float32))
    out = add_spikes(img, _one_star(cy=24, cx=24), 1.0, 1, 0.0)
    assert out.data.ndim == 2
    assert out.data.max() > 0.05


def test_count_exceeding_star_list_is_safe():
    out = add_spikes(_dark(), _one_star(), 0.5, 50, 0.0).data   # only 1 star present
    assert np.all(np.isfinite(out))


def _field_with_a_blob(h=200, w=200):
    """A few genuine point stars plus one big diffuse blob — the case that put
    spikes where no star is. SEP ranks by INTEGRATED flux, so a 5,099-pixel
    nebula region outranked real stars (measured on NGC 281)."""
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.05, np.float32)
    for cy, cx in ((40, 40), (60, 150), (150, 60), (170, 170)):
        lum += 0.9 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.8 ** 2)))
    lum += 0.55 * np.exp(-(((yy - 100) ** 2 + (xx - 100) ** 2) / (2 * 22.0 ** 2)))  # the blob
    rng = np.random.default_rng(1)
    lum = np.clip(lum + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    return np.repeat(lum[:, :, None], 3, axis=2)


def test_detection_rejects_things_that_are_not_point_like():
    """A big diffuse region is not a star, however much total light it holds."""
    stars = detect_stars(_field_with_a_blob())
    assert stars, "the genuine stars must still be found"
    for s in stars:
        assert not (85 < s.x < 115 and 85 < s.y < 115), (
            f"a spike would be drawn on the diffuse blob at ({s.x:.0f}, {s.y:.0f})")


def test_detection_is_capped_so_a_rich_field_cannot_stall_the_preview():
    """Measured: SEP finds 4,887 objects on NGC 281, and drawing 2,000 spikes
    costs 1.7 s per slider tick on a 39.5 MP master. The cap is load-bearing."""
    from nocturne.core.star_spikes import _MAX_STARS
    rng = np.random.default_rng(2)
    h = w = 400
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.03, np.float32)
    for cy, cx in zip(rng.integers(5, h - 5, 300), rng.integers(5, w - 5, 300)):
        lum += 0.8 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.6 ** 2)))
    data = np.repeat(np.clip(lum, 0, 1)[:, :, None], 3, axis=2).astype(np.float32)
    assert len(detect_stars(data)) <= _MAX_STARS


def test_stars_are_centred_on_the_star_not_the_blob_barycentre():
    """Measured on NGC 281 with the isophotal barycentre: 11 of 100 stars were
    more than 1 px off and the worst was 3.08 px, against arms 1.4 px thick."""
    # A POPULATED field, not one star on a flat background. SEP's background box
    # is 64 px, so a lone star inflates its own box and the model is fitted to
    # the thing it is meant to subtract: on such a frame SEP reported a sigma-2
    # star as a=68 b=62 centred 55 px away. That measures the background
    # estimator, not the centring this test is about.
    h = w = 300
    yy, xx = np.mgrid[0:h, 0:w]
    truth = [(60, 80), (150, 210), (230, 120), (100, 250), (200, 60)]
    lum = np.full((h, w), 0.04, np.float32)
    for cy, cx in truth:
        lum += 0.9 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.8 ** 2)))
    rng = np.random.default_rng(4)
    for cy, cx in zip(rng.integers(5, h - 5, 60), rng.integers(5, w - 5, 60)):
        lum += 0.25 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.6 ** 2)))
    lum = np.clip(lum + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    stars = detect_stars(np.repeat(lum[:, :, None], 3, axis=2))
    assert stars, "no stars found in a populated field"
    for cy, cx in truth:
        near = min(stars, key=lambda s: (s.x - cx) ** 2 + (s.y - cy) ** 2)
        off = np.hypot(near.x - cx, near.y - cy)
        assert off <= 1.0, f"star at ({cx}, {cy}) drawn {off:.2f} px away"


def _populated(extra=None, h=300, w=300, seed=7):
    """A field SEP can estimate a background on, plus whatever `extra` adds."""
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.04, np.float32)
    rng = np.random.default_rng(seed)
    for cy, cx in zip(rng.integers(5, h - 5, 60), rng.integers(5, w - 5, 60)):
        lum += 0.25 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.6 ** 2)))
    if extra is not None:
        lum = extra(lum, yy, xx)
    lum = np.clip(lum + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    return np.repeat(lum[:, :, None], 3, axis=2)


def test_the_centre_comes_from_the_windowed_centroid_not_the_barycentre():
    """A STRUCTURAL guard, and deliberately so.

    I could not build a synthetic case that discriminates: with clean gaussians,
    any wing mild enough to survive the elongation filter shifts the barycentre
    by under 0.65 px, and on merged pairs winpos is sometimes the WORSE of the
    two. Real stars are messier than a gaussian, and that is where it pays.

    Measured on real masters, offset from the star's brightest pixel:

        NGC 281    old 0.62 px, 7/50 over 1 px  ->  0.44 px, 0/50
        IC 1396A   old 0.73 px, 9/50            ->  0.54 px, 3/50

    Filtering does most of that on NGC 281 and winpos does most of it on
    IC 1396A, so both earn their place. Since the numbers cannot be reproduced
    in a test, this pins that winpos is WIRED IN and records them here instead
    of asserting an improvement no fixture can show.
    """
    import sep
    calls = []
    real = sep.winpos

    def spy(*a, **kw):
        calls.append(a)
        return real(*a, **kw)

    sep.winpos = spy
    try:
        stars = detect_stars(_populated())
    finally:
        sep.winpos = real
    assert stars, "nothing detected"
    assert calls, "detect_stars must centre with sep.winpos, not the barycentre"


def test_a_compact_bright_star_outranks_a_broad_dim_one():
    """Ranking, isolated from the size filter. Both of these survive filtering;
    the broad one holds MORE integrated flux while being far less bright. Sorting
    by flux put it first, which is how diffuse things got spikes."""
    def add(lum, yy, xx):
        lum += 0.95 * np.exp(-(((yy - 80) ** 2 + (xx - 80) ** 2) / (2 * 1.6 ** 2)))
        lum += 0.42 * np.exp(-(((yy - 220) ** 2 + (xx - 220) ** 2) / (2 * 4.5 ** 2)))
        return lum
    stars = detect_stars(_populated(add))
    assert stars, "nothing detected"
    top = stars[0]
    assert abs(top.x - 80) <= 3 and abs(top.y - 80) <= 3, (
        f"brightest should be the compact star at (80, 80), got "
        f"({top.x:.0f}, {top.y:.0f})")


def test_star_colour_comes_from_the_wings_not_the_blown_core():
    """Measured on NGC 281: the colour spread of the tint sampled at the core is
    0.001 — pure white — because 38 of 40 bright stars are saturated in all three
    channels there. A 5-9 px annulus gives 0.109, about a hundred times more.
    """
    h = w = 200
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.03, np.float32)
    rng = np.random.default_rng(11)
    for cy, cx in zip(rng.integers(5, h - 5, 40), rng.integers(5, w - 5, 40)):
        lum += 0.2 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.6 ** 2)))
    # a RED star: blown white at the core, red in the wings — exactly the case
    core = np.exp(-(((yy - 100) ** 2 + (xx - 100) ** 2) / (2 * 2.6 ** 2)))
    # ALL THREE channels clip at the centre, so the core is pure white and the
    # only colour left is in the wings — which is what a real bright star does
    # (38 of 40 measured on NGC 281 were saturated in all three at the core).
    data = np.stack([np.clip(lum + core * 3.0, 0, 1),
                     np.clip(lum + core * 1.7, 0, 1),
                     np.clip(lum + core * 1.25, 0, 1)], axis=2).astype(np.float32)
    stars = detect_stars(data)
    near = min(stars, key=lambda s: (s.x - 100) ** 2 + (s.y - 100) ** 2)
    assert np.hypot(near.x - 100, near.y - 100) < 3, "the red star was not found"
    r, g, b = near.color
    assert r > g > b, f"a red star must give a red tint, got {near.color}"
    assert (max(near.color) - min(near.color)) > 0.15, (
        f"tint is almost white ({near.color}) — still sampling the blown core")


def test_variation_is_deterministic_for_a_given_star():
    """The jitter must come from the star's own position, not a fresh random
    draw. A per-render seed would reshuffle every spike each time any OTHER
    slider moved, and the preview would stop matching what Apply produces."""
    from nocturne.core.star_spikes import add_spikes
    stars = detect_stars(_populated())
    img = AstroImage(_populated(), is_linear=False)
    a = add_spikes(img, stars, 0.7, 8, 0.0, 1.0, variation=0.6).data
    b = add_spikes(img, stars, 0.7, 8, 0.0, 1.0, variation=0.6).data
    assert np.array_equal(a, b), "two identical renders must be identical"


def test_variation_actually_makes_the_spikes_differ():
    """At 0 they are stamped from one template, which is what reads as artificial."""
    from nocturne.core.star_spikes import add_spikes
    stars = detect_stars(_populated())
    img = AstroImage(_populated(), is_linear=False)
    flat = add_spikes(img, stars, 0.7, 8, 0.0, 1.0, variation=0.0).data
    varied = add_spikes(img, stars, 0.7, 8, 0.0, 1.0, variation=0.8).data
    assert not np.array_equal(flat, varied), "variation must change the drawing"
    assert np.abs(varied - flat).max() > 0.05, "and change it visibly"
