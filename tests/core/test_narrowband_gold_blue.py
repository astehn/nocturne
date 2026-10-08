"""The "SHO-style (gold and blue)" palette (spec 2026-10-08, D1-D6), and the
guard that adding it left the three old palettes' pixels exactly where they were."""
import hashlib
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


def _with_oxygen_core(data, amp=0.1):
    h, w = data.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    core = amp * np.exp(-((xx - 500) ** 2 + (yy - 360) ** 2) / (2 * 60 ** 2))
    out = data.copy()
    out[..., 1] += core
    out[..., 2] += core
    return np.clip(out, 0, 1).astype(np.float32), ((xx - 500) ** 2 + (yy - 360) ** 2) < 30 ** 2


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
    assert stats.spread < nb.GB_FLOOR_SPREAD_LO          # the fixture reaches the floor
    assert _blue_share(_engine(data), data) < 0.02
    # Same image without the floor: relative colouring paints noise blue.
    monkeypatch.setattr(nb, "GB_FLOOR_SPREAD_LO", 0.0)
    monkeypatch.setattr(nb, "GB_FLOOR_SPREAD_HI", 0.0)
    assert _blue_share(_engine(data), data) > 0.10


def test_a_real_oxygen_core_stays_blue_through_the_floor():
    data, core = _with_oxygen_core(_pure_ha())
    stats = gold_blue_stats(AstroImage(data, is_linear=False))
    assert stats.spread >= nb.GB_FLOOR_SPREAD_HI and stats.blue_floor == 1.0
    h, s = _hsv(_engine(data))
    assert 196 <= np.median(h[core]) <= 225
    assert np.median(s[core]) > 0.3


def test_floor_ramps_between_its_two_calibration_points():
    lo, hi = nb.GB_FLOOR_SPREAD_LO, nb.GB_FLOOR_SPREAD_HI
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
    data = _with_oxygen_core(_pure_ha(360, 640))[0]
    img = AstroImage(data, is_linear=False)
    st = gold_blue_stats(img)
    p = palette_defaults(GOLD_BLUE)
    shifted = GoldBlueStats(st.match, st.centre + 0.5 * st.spread, st.spread, st.blue_floor)
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
    monkeypatch.setattr(nb, "nebula_mask", lambda rgb, protect: np.zeros(rgb.shape[:2], np.float32))
    st = gold_blue_stats(AstroImage(data, is_linear=False))
    assert np.isfinite([st.centre, st.spread, st.blue_floor]).all() and st.spread > 0


def test_mono_is_rejected():
    mono = AstroImage(np.zeros((8, 8), np.float32), is_linear=False)
    with pytest.raises(ValueError):
        render(mono, palette_defaults(GOLD_BLUE))
    with pytest.raises(ValueError):
        gold_blue_stats(mono)
