import numpy as np
import pytest

from nocturne.core.color import _background_mask, background_neutralize
from nocturne.core.image import AstroImage
from nocturne.core import star_balance as sb

CAST = np.array([1.40, 1.00, 0.86], np.float32)


def _field(n_stars=150, cast=CAST, nebula=True, border=0, seed=3):
    rng = np.random.default_rng(seed)
    h, w = 500, 600
    d = 0.02 + rng.normal(0, 0.0005, (h, w, 3)).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    pos = []
    while len(pos) < n_stars:
        x, y = rng.uniform(20, w - 20), rng.uniform(20, h - 20)
        if all((x - a) ** 2 + (y - b) ** 2 > 400 for a, b in pos):
            pos.append((x, y))
    amps = rng.uniform(0.05, 0.4, n_stars)
    for i, (x, y) in enumerate(pos):
        x0, y0 = int(x), int(y)
        sl = (slice(y0 - 8, y0 + 9), slice(x0 - 8, x0 + 9))
        g = np.exp(-((xx[sl] - x) ** 2 + (yy[sl] - y) ** 2) / (2 * 1.2 ** 2))
        d[sl] += (amps[i] * g)[..., None] * cast
        if nebula and i % 3 == 0:
            ny, nx = slice(y0 - 14, y0 + 15), slice(x0 - 14, x0 + 15)
            d[ny, nx, 0] += 0.01
    if border:
        d[:border] = 0
        d[:, :border] = 0
    return np.clip(d, 0, 1)


def _gains(d):
    r = sb.star_balance_gains(background_neutralize(d))
    assert r is not None
    return np.array(r.gains)


def test_gains_undo_a_known_star_cast():
    g = _gains(_field())
    np.testing.assert_allclose(g, 1 / CAST, rtol=0.03)


def test_nebula_under_stars_does_not_steer_the_gains():
    a, b = _gains(_field(nebula=True)), _gains(_field(nebula=False))
    np.testing.assert_allclose(a, b, rtol=0.01)


def test_sky_medians_are_unchanged_by_the_star_gains():
    d = _field()
    neut = background_neutralize(d)
    out, res = sb.apply_star_balance(AstroImage(d))
    assert res is not None
    mask = _background_mask(neut.mean(axis=2))
    before = [np.median(neut[..., c][mask]) for c in range(3)]
    after = [np.median(out.data[..., c][mask]) for c in range(3)]
    np.testing.assert_allclose(after, before, rtol=1e-6, atol=0)
    # and the stars really did move
    assert not np.allclose(out.data, neut)


def test_a_black_border_stays_black_and_does_not_move_the_gains():
    clean = _field()
    d = _field(border=40)
    out, res = sb.apply_star_balance(AstroImage(d))
    assert res is not None
    assert (out.data[:40] == 0).all() and (out.data[:, :40] == 0).all()
    np.testing.assert_allclose(_gains(d), _gains(clean), rtol=0.01)


def test_too_few_stars_gives_none_and_sky_balance():
    d = _field(n_stars=5)
    assert sb.star_balance_gains(background_neutralize(d)) is None
    out, res = sb.apply_star_balance(AstroImage(d))
    assert res is None
    np.testing.assert_array_equal(out.data, background_neutralize(d))


def test_absurd_gains_give_none():
    d = _field(cast=np.array([4.0, 1.0, 0.86], np.float32))
    assert sb.star_balance_gains(background_neutralize(d)) is None


def test_deterministic():
    d = _field()
    a, _ = sb.apply_star_balance(AstroImage(d))
    b, _ = sb.apply_star_balance(AstroImage(d))
    assert a.data.tobytes() == b.data.tobytes()


def test_mono_is_untouched():
    m = np.random.default_rng(0).random((20, 20)).astype(np.float32)
    out, res = sb.apply_star_balance(AstroImage(m))
    assert res is None
    np.testing.assert_array_equal(out.data, m)


def test_unknown_version_raises():
    with pytest.raises(ValueError):
        sb.apply_star_balance(AstroImage(_field(n_stars=5)), version=99)
