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
