"""The "SHO-style (gold and blue)" palette (spec 2026-10-08, D1-D6), and the
guard that adding it left the three old palettes' pixels exactly where they were."""
import dataclasses
import hashlib
import os
import itertools

import numpy as np
import pytest

from nocturne.core import narrowband as nb
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import (
    GOLD_BLUE, GOLD_BLUE_OXYGEN_DEFAULT, GoldBlueStats, NarrowbandParams,
    gold_blue_stats, palette_defaults, render,
)

OLD_PALETTES = ("HOO", "Pseudo-SHO", "Pseudo-bicolor")


# --- D1: the old palettes render byte-identically --------------------------

def _old_fixture():
    rng = np.random.default_rng(20261008)
    h, w = 48, 64
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ha = 0.08 + 0.7 * np.exp(-((xx - 22) ** 2 + (yy - 20) ** 2) / 180.0)
    oiii = 0.06 + 0.35 * np.exp(-((xx - 44) ** 2 + (yy - 28) ** 2) / 120.0) + 0.1 * ha
    data = np.stack([ha, oiii * 1.05, oiii * 0.95], 2) + 0.015 * rng.standard_normal((h, w, 3))
    data[10, 50] = data[11, 50] = 0.98
    return AstroImage(np.clip(data, 0, 1).astype(np.float32), is_linear=False)


_OLD_VARIANTS = [
    {},
    dict(oxygen_strength=1.3, saturation=1.2, lightness_preserve=True, protect_background=0.0),
    dict(blend_amount=0.2, highlight_reduction=3.0, brightness=1.4, scnr=False, blackpoint=0.5),
    dict(protect_background=0.8, oxygen_strength=0.5, highlight_recover=1.2),
]

# sha256 of render(...).data, captured at 9e1c6ae (v0.49.0) BEFORE this palette
# existed. Stored projects and recipes replay through exactly this path.
_OLD_HASHES = {
    ("HOO", 0, True): "bda49f00b2ef1295fd497ff8b543aedb230be9670ed12b0e96d7d586cd93c00c",
    ("HOO", 0, False): "16973273a069f797fbc79d27c622cf78a9ecea940ef27b5df5c5c7b89a57727b",
    ("HOO", 1, True): "855ee854e5f3c9a79a6ed4772baee4b57530849dfc7170112a94df9fa254b03a",
    ("HOO", 1, False): "9efa9186576ecd426f86ff6e132abad0da250447e17ad8a42f5188631b80be82",
    ("HOO", 2, True): "47680611b2e13998a12cf91af3da0ef7248ee7061a07886613e7c46ab2e6af0a",
    ("HOO", 2, False): "14fae2cdd28abb2839dbda66f25bc90d75258228f48b0037b421a912aed7f386",
    ("HOO", 3, True): "b44bc2ec08645deb6c021c3d5d8bdae5e2c5a028150eedce8068fcff3b3ab2df",
    ("HOO", 3, False): "c277eaba63fe2310167ff54d65b549928bc021f5590965248bd943006f9efbb3",
    ("Pseudo-SHO", 0, True): "35063e33eb66bfa3798782b688375fb553d191002d5588051c3de242e57fec14",
    ("Pseudo-SHO", 0, False): "586fc33aab904e3d91b5985df092751033dac5a6e321e4e72fae4b30312a9fbf",
    ("Pseudo-SHO", 1, True): "8200409b5db7a56083236303b7ecefb00320b350dad037603b70448bc6c46f1d",
    ("Pseudo-SHO", 1, False): "6a96ac1b95499b4995d1a01873a38cb9a698910923f862a8867e050ccb8997db",
    ("Pseudo-SHO", 2, True): "c49a71cfe60f783b2b97990898984950f9e49a1cb6d2f8b2765cf25fdbad6930",
    ("Pseudo-SHO", 2, False): "10e9da2168eb66fbfe9ef7c5d5ebf8dd71620c1fc7c63ec7b01ad9a1a101a931",
    ("Pseudo-SHO", 3, True): "a862bba1cfad138616b76ac947f999659f9161e1644036b270bc37bd6b7a2289",
    ("Pseudo-SHO", 3, False): "6cf5af3939b311492c214022db57832a2277908144db5a514cec2980eca4aa59",
    ("Pseudo-bicolor", 0, True): "dd2d6fb7a9a42540332e3aab6262a50061d865b3dc4e1c2c9eabf200a6862317",
    ("Pseudo-bicolor", 0, False): "fee7385a6cbca657147b2a219bdd4b72db2e223b87e541dc19b80292a3320bac",
    ("Pseudo-bicolor", 1, True): "deefa30eea951ab98fe68304d660a8ea6bb96fa147eecd4d7396a87a6fb3b39b",
    ("Pseudo-bicolor", 1, False): "5b2e3741af96339c9bb61317b9b4052f4116b05524bb27cfd7f509c1f3026599",
    ("Pseudo-bicolor", 2, True): "effff9a75bb2ca2fa40ced3ee4671fe592c5ec838cee4e93ba9d6a2d277d1e26",
    ("Pseudo-bicolor", 2, False): "b148b14001bd0bb9d3f2c5402d9de457e7278b6836dc15c3e7289c588570d38c",
    ("Pseudo-bicolor", 3, True): "d6db9041222e16efec8c0191c064f3e0f98e12aef5514f78a042757a48deeaa4",
    ("Pseudo-bicolor", 3, False): "02cde568bfd1a3b56e5fafb7ffe3ac53804b75891ad448b905e4640fc7b3f0d8",
}


@pytest.mark.filterwarnings("ignore:Conversion from CIE-LAB")
def test_old_palettes_render_byte_identically_to_before_this_palette():
    img = _old_fixture()
    for pal, (i, v), stars in itertools.product(OLD_PALETTES, enumerate(_OLD_VARIANTS), (True, False)):
        out = render(img, NarrowbandParams(palette=pal, **v), has_stars=stars).data
        got = hashlib.sha256(np.ascontiguousarray(out).tobytes()).hexdigest()
        assert got == _OLD_HASHES[(pal, i, stars)], f"{pal} variant {i} has_stars={stars} moved"


def test_old_palettes_start_from_the_same_defaults():
    for pal in OLD_PALETTES:
        assert palette_defaults(pal) == NarrowbandParams(palette=pal)
    assert NarrowbandParams().oxygen_strength == 0.85          # the old default, untouched


def test_new_palette_defaults_carry_its_own_oxygen_and_nothing_else_odd():
    p = palette_defaults(GOLD_BLUE)
    assert p.palette == GOLD_BLUE
    assert p.oxygen_strength == GOLD_BLUE_OXYGEN_DEFAULT == 0.60
    assert GOLD_BLUE in nb.PALETTES and GOLD_BLUE in nb.PALETTE_DESCRIPTIONS
    assert GOLD_BLUE not in nb.PALETTES_USING_BLEND


# --- helpers ---------------------------------------------------------------

def _hsv(a):
    a = np.clip(a, 0, 1)
    mx, mn = a.max(2), a.min(2)
    c = mx - mn
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    cc = np.maximum(c, 1e-9)
    h = np.where(mx == r, ((g - b) / cc) % 6, np.where(mx == g, (b - r) / cc + 2, (r - g) / cc + 4)) * 60
    h = np.where(c > 1e-9, h, 0)
    s = np.where(mx > 1e-9, c / np.maximum(mx, 1e-9), 0)
    return h, s


def _pure_ha(h=720, w=1280, noise=0.003, seed=1):
    """Hydrogen only: the OIII planes are the 12.7% IMX585 leak plus background
    and noise, so nothing in them varies independently of Ha."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ha = 0.08 + 0.75 * np.exp(-((xx - 0.4 * w) ** 2 + (yy - 0.5 * h) ** 2) / (2 * (0.18 * w) ** 2)) \
        + 0.25 * np.exp(-((xx - 0.7 * w) ** 2 + (yy - 0.3 * h) ** 2) / (2 * (0.08 * w) ** 2))
    o = 0.08 + 0.127 * (ha - 0.08)
    data = np.stack([ha, o, o], 2) + noise * rng.standard_normal((h, w, 3))
    return np.clip(data, 0, 1).astype(np.float32)


def _with_oxygen_core(data, amp=0.1, cx=500, cy=360):
    h, w = data.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    core = amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 60 ** 2))
    out = data.copy()
    out[..., 1] += core
    out[..., 2] += core
    return np.clip(out, 0, 1).astype(np.float32), ((xx - cx) ** 2 + (yy - cy) ** 2) < 30 ** 2


def _blue_share(out, original):
    """Visibly blue pixels as a share of the nebula (the 40% protect mask)."""
    h, s = _hsv(out)
    neb = nb.nebula_mask(original, 0.4) > 0.5
    return float(((h >= 165) & (h < 260) & (s > 0.15) & neb).sum() / neb.sum())


def _engine(data, **kw):
    """The palette's own colour, without the protect-background blend."""
    p = palette_defaults(GOLD_BLUE)
    p.protect_background = 0.0
    for k, v in kw.items():
        setattr(p, k, v)
    return render(AstroImage(data, is_linear=False), p, has_stars=False).data


# --- D4: the floor ---------------------------------------------------------

def test_pure_hydrogen_gets_almost_no_blue_and_the_floor_is_why(monkeypatch):
    data = _pure_ha()
    stats = gold_blue_stats(AstroImage(data, is_linear=False))
    assert stats.evidence < nb.GB_FLOOR_EVIDENCE_LO       # the fixture reaches the floor
    assert _blue_share(_engine(data), data) < 0.02
    # Same image without the floor: relative colouring paints noise blue.
    monkeypatch.setattr(nb, "GB_FLOOR_EVIDENCE_LO", 0.0)
    monkeypatch.setattr(nb, "GB_FLOOR_EVIDENCE_HI", 0.0)
    # 0.066 since _GB_MIN_SPREAD damped the noise (it was > 0.10 before).
    assert _blue_share(_engine(data), data) > 0.04


def test_a_real_oxygen_core_stays_blue_through_the_floor():
    # Off the hydrogen peak: an oxygen core exactly concentric with it is a
    # rising function of Ha, which the evidence cannot tell from leak + stretch
    # (scores 2.2 there, 18.7 at this position; see GB_FLOOR_EVIDENCE_LO).
    data, core = _with_oxygen_core(_pure_ha(), cx=650, cy=300)
    stats = gold_blue_stats(AstroImage(data, is_linear=False))
    assert stats.evidence >= nb.GB_FLOOR_EVIDENCE_HI and stats.blue_floor == 1.0
    h, s = _hsv(_engine(data))
    assert 196 <= np.median(h[core]) <= 225
    assert np.median(s[core]) > 0.3


def test_floor_ramps_between_its_two_calibration_points():
    lo, hi = nb.GB_FLOOR_EVIDENCE_LO, nb.GB_FLOOR_EVIDENCE_HI
    assert nb._blue_floor(lo) == 0.0 and nb._blue_floor(hi) == 1.0
    assert nb._blue_floor((lo + hi) / 2) == pytest.approx(0.5)


# --- no green (Review Focus 4) ---------------------------------------------

@pytest.mark.parametrize("oxygen,saturation", [(0.3, 0.85), (0.6, 0.85), (2.0, 1.0), (1.0, 0.5)])
def test_never_paints_green(oxygen, saturation):
    rng = np.random.default_rng(7)
    base = _with_oxygen_core(_pure_ha(360, 640, noise=0.02), amp=0.3)[0]
    noise = rng.random(base.shape).astype(np.float32) * 0.3
    data = np.clip(base * 0.8 + noise, 0, 1).astype(np.float32)
    h, s = _hsv(_engine(data, oxygen_strength=oxygen, saturation=saturation))
    green = (h >= 75) & (h < 165) & (s > 0.10)
    assert green.mean() < 0.001, f"{green.mean():.4%} green"


# --- D6: preview equals Apply ----------------------------------------------

def test_stats_copy_is_the_previews_downscale():
    pytest.importorskip("PySide6")
    from nocturne.ui.preview import downscale
    rng = np.random.default_rng(3)
    for shape in [(100, 90, 3), (1258, 1545, 3), (2160, 3840, 3), (1301, 1999, 3)]:
        data = rng.random(shape).astype(np.float32)
        want = downscale(AstroImage(data, is_linear=False)).data
        assert np.array_equal(nb._stats_copy(data), want)


def test_preview_and_full_size_measure_identical_stats():
    pytest.importorskip("PySide6")
    from nocturne.ui.preview import downscale
    data = _with_oxygen_core(_pure_ha())[0]
    full = AstroImage(data, is_linear=False)
    preview = downscale(full)
    assert preview.data.shape[0] < data.shape[0]           # a real downscale happened
    assert gold_blue_stats(full) == gold_blue_stats(preview)
    p = palette_defaults(GOLD_BLUE)
    # Apply without stats == Apply handed the preview's stats, to the bit.
    assert np.array_equal(render(full, p, has_stars=False).data,
                          render(full, p, has_stars=False, stats=gold_blue_stats(preview)).data)


def test_full_size_pixel_gets_the_preview_pixels_colour_given_the_same_stats():
    """Per-pixel formula identical: a full-size image made of the preview's
    pixels, each repeated over its block, renders to the preview, block for block."""
    pytest.importorskip("PySide6")
    from nocturne.ui.preview import downscale
    data = _with_oxygen_core(_pure_ha())[0]
    small = downscale(AstroImage(data, is_linear=False))
    k = 2
    assert data.shape[1] // small.data.shape[1] == k
    big = np.repeat(np.repeat(small.data, k, 0), k, 1)
    stats = gold_blue_stats(small)
    assert gold_blue_stats(AstroImage(big, is_linear=False)) == stats
    p = palette_defaults(GOLD_BLUE)
    p.protect_background = 0.0
    a = render(small, p, has_stars=False, stats=stats).data
    b = render(AstroImage(big, is_linear=False), p, has_stars=False, stats=stats).data
    assert np.array_equal(b[::k, ::k], a)


def test_passed_stats_are_what_the_render_uses():
    # Real oxygen, so the floor is open: under a closed floor the render is one
    # even gold and the centre rightly has no effect.
    data = _with_oxygen_core(_pure_ha(360, 640), amp=0.3)[0]
    img = AstroImage(data, is_linear=False)
    st = gold_blue_stats(img)
    assert st.blue_floor == 1.0
    p = palette_defaults(GOLD_BLUE)
    shifted = dataclasses.replace(st, centre=st.centre + 0.5 * st.spread)
    assert not np.array_equal(render(img, p, stats=st).data, render(img, p, stats=shifted).data)


# --- the sliders -------------------------------------------------------------

def test_more_oxygen_turns_more_of_the_picture_blue():
    data = _with_oxygen_core(_pure_ha(360, 640), amp=0.3)[0]
    shares = [_blue_share(_engine(data, oxygen_strength=o), data) for o in (0.3, 0.6, 1.0, 1.5)]
    assert shares == sorted(shares) and shares[-1] > shares[0] + 0.05


def test_saturation_zero_keeps_only_the_pictures_lightness():
    data = _with_oxygen_core(_pure_ha(360, 640), amp=0.3)[0]
    out = _engine(data, saturation=0.0)
    assert float((out.max(2) - out.min(2)).max()) < 2e-3


def test_keeps_the_pictures_own_lightness():
    data = _with_oxygen_core(_pure_ha(360, 640), amp=0.3)[0]
    out = _engine(data)
    L_in = nb._srgb_to_oklab(data)[..., 0]
    L_out = nb._srgb_to_oklab(out)[..., 0]
    assert np.percentile(np.abs(L_out - L_in), 99) < 0.01


def test_blend_and_preserve_lightness_do_not_reach_this_palette():
    data = _with_oxygen_core(_pure_ha(120, 160), amp=0.3)[0]
    img = AstroImage(data, is_linear=False)
    ref = render(img, palette_defaults(GOLD_BLUE)).data
    for kw in (dict(blend_amount=0.0), dict(blend_amount=1.0), dict(lightness_preserve=True)):
        p = palette_defaults(GOLD_BLUE)
        for k, v in kw.items():
            setattr(p, k, v)
        assert np.array_equal(render(img, p).data, ref), kw


def test_brightness_and_tame_still_act_on_this_palette():
    data = _with_oxygen_core(_pure_ha(120, 160), amp=0.3)[0]
    img = AstroImage(data, is_linear=False)
    ref = render(img, palette_defaults(GOLD_BLUE)).data
    for kw in (dict(brightness=1.5), dict(highlight_reduction=3.0)):
        p = palette_defaults(GOLD_BLUE)
        for k, v in kw.items():
            setattr(p, k, v)
        assert not np.array_equal(render(img, p).data, ref), kw


# --- degenerate inputs -------------------------------------------------------

@pytest.mark.parametrize("data", [
    np.full((64, 64, 3), 0.3, np.float32),                       # flat
    np.zeros((64, 64, 3), np.float32),                           # black
    np.ones((64, 64, 3), np.float32),                            # white
    np.random.default_rng(0).random((8, 8, 3)).astype(np.float32),   # 8x8
    np.random.default_rng(1).random((1, 1, 3)).astype(np.float32),   # one pixel
])
@pytest.mark.parametrize("has_stars", [True, False])
def test_degenerate_inputs_stay_finite_and_in_range(data, has_stars):
    out = render(AstroImage(data, is_linear=False), palette_defaults(GOLD_BLUE),
                 has_stars=has_stars).data
    assert out.shape == data.shape and out.dtype == np.float32
    assert np.isfinite(out).all() and out.min() >= 0.0 and out.max() <= 1.0


def test_an_empty_nebula_mask_falls_back_to_the_whole_picture(monkeypatch):
    data = _with_oxygen_core(_pure_ha(120, 160), amp=0.3)[0]
    monkeypatch.setattr(nb, "nebula_mask", lambda rgb, protect, caps=None, data=None: np.zeros(rgb.shape[:2], np.float32))
    st = gold_blue_stats(AstroImage(data, is_linear=False))
    assert np.isfinite([st.centre, st.spread, st.blue_floor]).all() and st.spread > 0


def test_mono_is_rejected():
    mono = AstroImage(np.zeros((8, 8), np.float32), is_linear=False)
    with pytest.raises(ValueError):
        render(mono, palette_defaults(GOLD_BLUE))
    with pytest.raises(ValueError):
        gold_blue_stats(mono)


# --- review round 1: noise-proof floor, and the tuned shape pinned ----------

@pytest.mark.parametrize("shape,step", [((540, 960), 1), ((720, 1280), 2), ((1080, 1920), 3)])
@pytest.mark.parametrize("noise", [0.003, 0.006, 0.01])
def test_pure_hydrogen_stays_gold_whatever_the_noise_and_size(shape, step, noise):
    data = _pure_ha(*shape, noise=noise)
    assert max(shape) // nb._GB_STATS_EDGE == step                    # the step we mean to test
    assert gold_blue_stats(AstroImage(data, is_linear=False)).blue_floor == 0.0
    assert _blue_share(_engine(data), data) < 0.02


@pytest.mark.parametrize("shape", [(720, 1280), (1440, 2560)])
def test_pure_hydrogen_is_gold_all_over_not_gold_speckled_with_grey(shape):
    """Final review I-1: with the floor closed the oxygen side used to go grey,
    and with a stats-copy spread far below one pixel's noise in t, noise picked
    the side per pixel. At 1440x2560, 44% of the nebula came out grey and
    neighbouring pixels jumped by half the gold's chroma."""
    data = _pure_ha(*shape)
    assert gold_blue_stats(AstroImage(data, is_linear=False)).blue_floor == 0.0
    lab = nb._srgb_to_oklab(_engine(data))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    neb = nb.nebula_mask(data, 0.4) > 0.5
    assert (lab[..., 2][neb] >= 0).mean() > 0.99, "hydrogen-only must be on the gold side"
    assert (chroma[neb] < 0.01).mean() < 0.05, "grey pixels inside a hydrogen nebula"
    jump = np.abs(np.diff(chroma, axis=1))[neb[:, 1:] & neb[:, :-1]].mean()
    assert jump < 0.25 * chroma[neb].mean(), f"speckle: neighbour jump {jump:.4f}"


def test_protect_default_is_the_palettes_own_and_the_old_ones_keep_theirs():
    assert palette_defaults(GOLD_BLUE).protect_background == 0.20
    for pal in OLD_PALETTES:
        assert palette_defaults(pal).protect_background == 0.40


def _blue_side(out):
    """Pixels on the oxygen side by DIRECTION (OKLab b < 0), whatever their chroma."""
    return int((nb._srgb_to_oklab(out)[..., 2] < -1e-3).sum())


def test_less_oxygen_moves_the_balance_point_toward_oxygen():
    data = _with_oxygen_core(_pure_ha(360, 640), amp=0.3)[0]
    sides = [_blue_side(_engine(data, oxygen_strength=o)) for o in (0.3, 0.6, 1.0)]
    assert sides[0] < sides[1] < sides[2]
    assert sides[0] < 0.8 * sides[2]


def test_star_taper_drains_the_brightest_only_in_a_layer_that_still_has_stars():
    data, core = _with_oxygen_core(_pure_ha(360, 640), amp=0.3)
    data[175:185, 495:505] = (0.92, 1.0, 1.0)                         # a bright, oxygen-side "star"
    img = AstroImage(data, is_linear=False)
    p = palette_defaults(GOLD_BLUE)
    p.protect_background = 0.0
    bright = nb._srgb_to_oklab(data)[..., 0] > 0.95
    assert bright.sum() >= 50

    def chroma(has_stars):
        lab = nb._srgb_to_oklab(render(img, p, has_stars=has_stars).data)
        return np.hypot(lab[..., 1], lab[..., 2])[bright]
    # The taper is linear to zero at L = 1 over 0.15 of L, so at L ~0.98 it
    # keeps ~13% of the colour; without stars nothing holds it back.
    with_stars, without = chroma(True), chroma(False)
    assert np.median(without) > 0.01
    assert (with_stars <= 0.25 * without).all()


# Exact-t probe: a zero pedestal makes t = O/(Ha+O) scale-invariant, and centre 0.5,
# spread 0.5 make d = clip(4t-2, -1, 1), so each pixel's chroma is the formula's.
_PROBE = GoldBlueStats(pedestal=(0.0, 0.0), centre=0.5, spread=0.5, evidence=100.0, blue_floor=1.0)


def _probe_chroma(pixels, **kw):
    p = NarrowbandParams(palette=GOLD_BLUE, oxygen_strength=1.0, saturation=0.425,
                         protect_background=0.0, **kw)
    data = np.array([pixels], dtype=np.float32)
    lab = nb._srgb_to_oklab(render(AstroImage(data, is_linear=False), p,
                                   has_stars=False, stats=_PROBE).data)
    return np.hypot(lab[0, :, 1], lab[0, :, 2]), nb._srgb_to_oklab(data)[0, :, 0]


def test_colour_ramp_shape_is_gamma_0_6():
    # t = 0.25 -> d = -1 (full), t = 0.4375 -> d = -0.25 (both gold, both bright)
    c, L = _probe_chroma([(0.9, 0.3, 0.3), (0.9, 0.7, 0.7)])
    assert (L >= nb._GB_DARK_L).all()
    assert c[1] / c[0] == pytest.approx(0.25 ** 0.6, rel=0.03)        # gamma 1.0 would give 0.25


def test_gold_is_0_70_of_the_blue_at_the_same_distance():
    c, L = _probe_chroma([(0.9, 0.3, 0.3), (0.3, 0.9, 0.9)])          # d = -1 and d = +1
    assert (L >= nb._GB_DARK_L).all()
    assert c[0] / c[1] == pytest.approx(0.70, rel=0.03)


def test_dark_parts_get_colour_in_proportion_to_their_lightness():
    c, L = _probe_chroma([(0.9, 0.3, 0.3), (0.27, 0.09, 0.09)])        # same t, darker
    assert L[1] < nb._GB_DARK_L <= L[0]
    assert c[1] / c[0] == pytest.approx(L[1] / nb._GB_DARK_L, rel=0.03)


# --- Task 3: tight crops (no sky in frame) ----------------------------------

def _nebula_frame(h=720, w=1280, seed=4, noise=0.003):
    """Neutral sky around a flat-topped hydrogen nebula with one broad oxygen
    region, so a crop inside the nebula has no sky at all."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) / h
    neb = np.exp(-(((xx - 0.89) / 0.42) ** 2 + ((yy - 0.5) / 0.3) ** 2) ** 2)
    ha = 0.08 + 0.45 * neb + 0.08 * neb * np.sin(11 * xx) * np.cos(7 * yy)
    ox = 0.10 * np.exp(-((xx - 0.80) ** 2 + (yy - 0.45) ** 2) / (2 * 0.12 ** 2)) * neb
    o = 0.08 + 0.127 * (ha - 0.08) + ox
    data = np.stack([ha, o, o], 2) + noise * rng.standard_normal((h, w, 3))
    return np.clip(data, 0, 1).astype(np.float32), neb, ((xx - 0.80) ** 2 + (yy - 0.45) ** 2) > 0.3 ** 2


def _cool(out):
    lab = nb._srgb_to_oklab(np.clip(out, 0, 1))
    return (np.hypot(lab[..., 1], lab[..., 2]) > 0.025) & (lab[..., 2] < 0)


def _still_blue(data, crop):
    """Of the crop region's blue in the full-frame render, the share still
    blue when the crop is rendered on its own (defaults)."""
    p = palette_defaults(GOLD_BLUE)
    full = render(AstroImage(data, is_linear=False), p, has_stars=False).data
    alone_img = AstroImage(np.ascontiguousarray(data[crop]), is_linear=False)
    alone = render(alone_img, p, has_stars=False).data
    blue_full = _cool(full[crop])
    assert blue_full.mean() > 0.1, "the crop must hold real blue in the full frame"
    return float((_cool(alone) & blue_full).sum() / blue_full.sum()), gold_blue_stats(alone_img)


def test_a_crop_with_no_sky_keeps_its_blue():
    data, _, _ = _nebula_frame()
    crop = np.s_[230:470, 470:800]
    assert data[crop].mean(2).min() > 0.15            # really no sky in the crop
    kept, st = _still_blue(data, crop)
    assert st.blue_floor == 1.0
    assert kept > 0.40                                 # 49% measured; 26% with the old mask


def test_faint_hydrogen_stays_gold_because_the_sky_pedestal_comes_off():
    """A neutral sky reads t = 0.5, far on the oxygen side; without the pedestal
    the faint rim of a hydrogen nebula went blue-grey (IC 1805's heart)."""
    data, neb, far = _nebula_frame()
    rim = (neb > 0.15) & (neb < 0.6) & far
    lab = nb._srgb_to_oklab(_engine(data))
    assert _cool(_engine(data))[rim].mean() < 0.05
    assert lab[..., 2][rim].mean() > 0.01               # gold side: +0.030 measured, -0.021 without


def test_the_floor_reads_oxygen_evidence_on_a_crop():
    """The old floor read the spread of t, which a tight crop shrinks (NGC 7000's
    Gulf crop: floor 0.00); the evidence of oxygen stays well clear of the ramp.
    His real crop is pinned in test_his_tight_crops_keep_their_blue."""
    data, _, _ = _nebula_frame()
    st = gold_blue_stats(AstroImage(np.ascontiguousarray(data[230:470, 470:800]), is_linear=False))
    assert st.evidence > 3 * nb.GB_FLOOR_EVIDENCE_HI and st.blue_floor == 1.0


# His five StarX-split exports, cached by the bench (never re-split). They live
# outside the repo; point NOCTURNE_NB_BENCH at the folder to run these. The
# synthetic stand-ins below cover the same behaviour everywhere.
_BENCH = os.environ.get(
    "NOCTURNE_NB_BENCH",
    "/private/tmp/claude-501/-Volumes-Work-Code-Editor/"
    "3c08bfe1-d115-45f9-abe8-0ea76caccfea/scratchpad/nbcache/")


def _bench_layer(name):
    path = os.path.join(_BENCH, name + ".starless.npy")
    if not os.path.exists(path):
        pytest.skip(f"bench-only: {path} not found — set NOCTURNE_NB_BENCH to the folder "
                    f"of his cached StarX layers (<NAME>.starless.npy) to run this")
    return np.load(path)


@pytest.mark.parametrize("name,box,minimum", [
    ("NGC7000", (0.00, 0.28, 0.25, 0.65), 0.55),       # Gulf tight: 67% now, 1% before
    ("NGC7000", (0.00, 0.35, 0.10, 0.75), 0.50),       # Gulf+Mexico: 63% now, 6% before
    ("IC1805", (0.45, 0.80, 0.25, 0.60), 0.45),        # heart core: 57% now, 14% before
])
def test_his_tight_crops_keep_their_blue(name, box, minimum):
    a = _bench_layer(name)
    h, w = a.shape[:2]
    x0, x1, y0, y1 = box
    kept, st = _still_blue(a, np.s_[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)])
    assert st.blue_floor == 1.0
    assert kept >= minimum


@pytest.mark.parametrize("crop,minimum", [
    (np.s_[230:470, 470:800], 0.40),     # inside the nebula, no sky: 49% measured
    (np.s_[100:620, 300:900], 0.75),     # wider, reaching the sky edge: 89%
])
def test_stand_in_crops_keep_their_blue(crop, minimum):
    """Runs everywhere: the synthetic counterpart of his tight crops."""
    data, _, _ = _nebula_frame()
    kept, st = _still_blue(data, crop)
    assert st.blue_floor == 1.0
    assert kept >= minimum


# --- review: black borders (he stacks UNTRIMMED) -----------------------------

def _black_border(a, frac):
    b = a.copy()
    k = max(1, int(round(frac * min(a.shape[:2]))))
    b[:k] = 0
    b[-k:] = 0
    b[:, :k] = 0
    b[:, -k:] = 0
    return b


def _black_corners(a, deg=6.0):
    """What a rotated crop leaves: black triangles in the corners."""
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.deg2rad(deg)
    xr = (xx - w / 2) * np.cos(t) + (yy - h / 2) * np.sin(t)
    yr = -(xx - w / 2) * np.sin(t) + (yy - h / 2) * np.cos(t)
    b = a.copy()
    b[~((np.abs(xr) <= w / 2 * 0.93) & (np.abs(yr) <= h / 2 * 0.93))] = 0
    return b


def _border_change(a, bordered):
    """OKLab colour difference over the data area between the frame with a
    black border and the same frame without one, and the border's brightest."""
    p = palette_defaults(GOLD_BLUE)
    ref = render(AstroImage(a, is_linear=False), p, has_stars=False).data
    out = render(AstroImage(bordered, is_linear=False), p, has_stars=False).data
    data = bordered.max(2) > nb._GB_DATA_EPS
    dE = np.sqrt(((nb._srgb_to_oklab(out) - nb._srgb_to_oklab(ref)) ** 2).sum(2))[data]
    return float(dE.mean()), float(np.percentile(dE, 99)), float(out[~data].max())


# Tolerance: on his five real layers (1/3/10% borders and 6 deg corners) the data
# area moved by mean dE <= 0.0013 and p99 <= 0.0095 after the fix, against mean
# up to 0.020 and p99 up to 0.099 before (1% of black made the sky level 0).
_BORDER_TOL = (0.002, 0.012)


@pytest.mark.parametrize("make", [lambda a: _black_border(a, 0.01), lambda a: _black_border(a, 0.03),
                                  lambda a: _black_border(a, 0.10), _black_corners],
                         ids=["border 1%", "border 3%", "border 10%", "rotated corners"])
def test_a_black_border_leaves_the_picture_as_it_was(make):
    data, neb, far = _nebula_frame()
    bordered = make(data)
    mean, p99, border_max = _border_change(data, bordered)
    assert mean < _BORDER_TOL[0] and p99 < _BORDER_TOL[1], (mean, p99)
    assert border_max == 0.0                                   # the border stays black
    # ...and the faint hydrogen, the first thing a lost sky level turns blue, stays gold
    rim = (neb > 0.15) & (neb < 0.6) & far & (bordered.max(2) > nb._GB_DATA_EPS)
    assert _cool(_engine(bordered))[rim].mean() < 0.05


@pytest.mark.parametrize("size,box", [((1080, 1920), np.s_[150:930, 300:1500]),
                                      ((540, 960), np.s_[75:465, 150:750])],
                         ids=["full size", "preview size"])
def test_a_border_around_nebula_that_fills_the_frame_does_not_bleed_in(size, box):
    """No sky at all, nebula to every edge, 10% black border: the blurs that
    feed the statistics and the protect mask are taken over the data only, so
    the border's zeros do not leak into the picture's edge. Measured p99 dE
    0.0084 at both sizes with data-only blurs, 0.0112 with plain ones (the
    preview size takes nebula_mask's direct-blur branch, full size the
    quarter-resolution one)."""
    d, _, _ = _nebula_frame(*size)
    fill = np.ascontiguousarray(d[box])
    mean, p99, border_max = _border_change(fill, _black_border(fill, 0.10))
    assert mean < 0.004 and p99 < 0.010, (mean, p99)
    assert border_max == 0.0


def test_the_sky_level_is_read_over_the_data_only():
    data, _, _ = _nebula_frame()
    plain = gold_blue_stats(AstroImage(data, is_linear=False))
    bordered = gold_blue_stats(AstroImage(_black_border(data, 0.03), is_linear=False))
    assert bordered.pedestal[0] > 0.05 and bordered.pedestal[1] > 0.05
    assert bordered.pedestal == pytest.approx(plain.pedestal, abs=0.005)


@pytest.mark.parametrize("name", ["IC1396A", "IC1805", "M16", "NGC6992", "NGC7000"])
def test_his_layers_ignore_a_black_border(name):
    a = _bench_layer(name)
    for bordered in (_black_border(a, 0.03), _black_border(a, 0.10), _black_corners(a)):
        mean, p99, border_max = _border_change(a, bordered)
        assert mean < _BORDER_TOL[0] and p99 < _BORDER_TOL[1], (name, mean, p99)
        assert border_max == 0.0


def test_flat_hydrogen_with_varying_oxygen_is_evidence():
    """A flat Ha plane used to short-circuit the evidence to 0, however much
    the oxygen varied."""
    rng = np.random.default_rng(1)
    h, w = 360, 640
    yy, xx = np.mgrid[0:h, 0:w] / h
    ha = np.full((h, w), 0.4, np.float32)
    o = 0.15 + 0.15 * np.exp(-((xx - 1) ** 2 + (yy - 0.5) ** 2) / 0.05)
    data = np.clip(np.stack([ha, o, o], 2) + 0.003 * rng.standard_normal((h, w, 3)), 0, 1)
    st = gold_blue_stats(AstroImage(data.astype(np.float32), is_linear=False))
    assert st.evidence > nb.GB_FLOOR_EVIDENCE_HI and st.blue_floor == 1.0


def test_noise_free_hydrogen_does_not_read_as_oxygen():
    """With no noise the residual's tiny width over a near-zero noise read as
    strong evidence (19 on a construction of NGC 6992); the noise floor stops it."""
    data = _pure_ha(noise=0.0)
    st = gold_blue_stats(AstroImage(data, is_linear=False))
    assert st.blue_floor == 0.0
    assert _blue_share(_engine(data), data) < 0.02


@pytest.mark.parametrize("m,noise", [(0.02, 0.0), (0.005, 1e-4)])
def test_a_stretched_pure_hydrogen_frame_does_not_read_as_oxygen(m, noise):
    """After a stretch OIII is a curve in Ha, not a line: a quadratic fit left
    that curve in the residual and scored it 7.6-9.1, i.e. full blue."""
    from nocturne.core.autostretch import _mtf
    lin = (_pure_ha(noise=0.0) - 0.07) * 0.05 + 0.002
    lin = lin + noise * np.random.default_rng(9).standard_normal(lin.shape)
    data = np.clip(_mtf(m, np.clip(lin, 0, 1)), 0, 1).astype(np.float32)
    assert gold_blue_stats(AstroImage(data, is_linear=False)).blue_floor == 0.0
    assert _blue_share(_engine(data), data) < 0.02


def test_oxygen_at_low_hydrogen_is_evidence_a_rising_fit_cannot_absorb():
    """Three flat blocks — sky, hydrogen, oxygen. Any curve through the three
    clusters (a quartic, or binned medians left free to fall) explains the
    oxygen block away (0.41 / 0.00); a fit made to RISE with Ha cannot."""
    ha = np.full((60, 120), 0.05, np.float32); oiii = np.full((60, 120), 0.04, np.float32)
    ha[10:50, 5:55], oiii[10:50, 5:55] = 0.75, 0.10
    ha[10:50, 65:115], oiii[10:50, 65:115] = 0.10, 0.75
    st = gold_blue_stats(AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False))
    assert st.evidence > 10 * nb.GB_FLOOR_EVIDENCE_HI


def test_a_small_bright_hydrogen_nebula_is_not_oxygen_at_its_brightest():
    """When the nebula is a few percent of the frame its brightest pixels lie
    beyond the last bin's centre; a fit held flat there left the brightest
    hydrogen as residual (his pure-hydrogen IC 1805 construction scored 7.9)."""
    rng = np.random.default_rng(5)
    h, w = 720, 1280
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ha = 0.08 + 0.85 * np.exp(-((xx - 640) ** 2 + (yy - 360) ** 2) / (2 * 40.0 ** 2))
    o = 0.08 + 0.3 * (ha - 0.08)
    data = np.clip(np.stack([ha, o, o], 2) + 0.003 * rng.standard_normal((h, w, 3)), 0, 1)
    st = gold_blue_stats(AstroImage(data.astype(np.float32), is_linear=False))
    assert st.evidence < nb.GB_FLOOR_EVIDENCE_LO
