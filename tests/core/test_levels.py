import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.levels import apply_levels, auto_levels


def test_identity():
    d = np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8)
    out = apply_levels(AstroImage(d), 0.0, 1.0, 1.0)
    assert np.allclose(out.data, d, atol=1e-6)


def test_raise_black_point_darkens():
    d = np.full((8, 8), 0.3, np.float32)
    out = apply_levels(AstroImage(d), 0.2, 1.0, 1.0)
    assert np.median(out.data) < 0.3


def test_gamma_above_one_brightens():
    d = np.full((8, 8), 0.3, np.float32)
    out = apply_levels(AstroImage(d), 0.0, 2.0, 1.0)
    assert np.median(out.data) > 0.3


def test_preserves_linear_flag_and_range():
    out = apply_levels(
        AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False),
        0.1, 1.5, 0.9,
    )
    assert out.is_linear is False
    assert out.data.min() >= 0 and out.data.max() <= 1


def _stretched():
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.25, 0.05, (64, 64, 3)).astype(np.float32), 0, 1)
    d[:2, :2] = 0.98  # a few bright pixels
    return d


def test_auto_levels_sane():
    d = _stretched()
    b, g, w = auto_levels(d)
    assert 0.0 <= b < w <= 1.0
    assert 0.4 <= g <= 2.5
    assert b < float(np.median(d)) < w


def _sky(d):
    """The background, not the whole frame: the median of the darker half."""
    lum = d.mean(axis=2) if d.ndim == 3 else d
    return float(np.median(lum[lum <= np.median(lum)]))


def test_auto_levels_does_not_re_brighten_the_background():
    """The stretch placed the background deliberately; Levels must not move it back up.

    autostretch targets a median of 0.25 (`_TARGET_BG`) and auto_levels used to
    re-target 0.35 with an adaptive gamma, so the two steps disagreed about how
    bright the sky should be and the second one won. Measured on six real
    masters, it lifted the sky +12% to +30% — the milky look Andreas rejected.
    """
    d = _stretched()
    before = _sky(d)
    out = apply_levels(AstroImage(d, is_linear=False), *auto_levels(d)).data
    assert _sky(out) <= before + 1e-6


def test_auto_levels_black_point_survives_a_mosaic_border():
    """A percentile black point is contaminated by non-image pixels.

    On Andreas' real M 31 mosaic 11.59% of the frame is empty border outside
    panel coverage, so the 1st percentile landed INSIDE the border and returned
    exactly 0.0 — the black point did nothing at all on any mosaic. A robust
    median-MAD estimator gave 0.1431 on the same frame.
    """
    d = _stretched()
    d[:, :8] = 0.0                      # 12.5% empty border, as a mosaic has
    black, _g, _w = auto_levels(d)
    assert black > 0.05, "the border swallowed the black point"


def test_auto_levels_blows_no_additional_star_cores():
    """Assert UNCHANGED, not 'not obviously wrong'.

    A flat 99.9th-percentile white point clipped ~0.08% of pixels to pure white
    on every real master — about 6,000 star cores, destroying their colour.
    Seestar cores do not saturate in the capture, so that colour is real data.
    """
    d = _stretched()
    d[10:12, 10:12] = (1.0, 0.85, 0.70)     # a bright star that still HAS colour
    before = int((d >= 0.999).all(axis=2).sum())
    out = apply_levels(AstroImage(d, is_linear=False), *auto_levels(d)).data
    assert int((out >= 0.999).all(axis=2).sum()) == before
