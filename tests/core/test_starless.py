import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.starless import split_stars


def _scene(h=200, w=200, seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    neb = 0.25 + 0.12 * np.exp(-(((yy - h // 2) ** 2 + (xx - w // 2) ** 2) / (2 * 50 ** 2)))
    img = neb + 0.02 * rng.standard_normal((h, w))
    stars = np.zeros((h, w), np.float32)
    for _ in range(60):
        cy, cx = rng.integers(8, h - 8), rng.integers(8, w - 8)
        stars += rng.uniform(0.2, 0.9) * np.exp(
            -(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * rng.uniform(0.9, 2.2) ** 2)))
    return np.clip(img + stars, 0, 1).astype(np.float32)


def test_screen_recombine_reconstructs_exactly():
    data = _scene()
    img = AstroImage(np.stack([data] * 3, axis=2), is_linear=False)
    starless, stars = split_stars(img)
    recon = 1.0 - (1.0 - starless.data) * (1.0 - stars.data)
    assert np.abs(recon - img.data).max() < 1e-4          # screen recombine == original


def test_starless_removes_star_peaks_keeps_nebula():
    data = _scene()
    img = AstroImage(np.stack([data] * 3, axis=2), is_linear=False)
    starless, _ = split_stars(img)
    assert starless.data.max() < img.data.max() - 0.05    # bright star peaks pulled down
    # a star-free nebula corner is essentially unchanged
    corner = (slice(0, 12), slice(0, 12))
    assert np.abs(starless.data[corner] - img.data[corner]).mean() < 0.02
    assert np.isfinite(starless.data).all()


def test_no_stars_is_identity_split():
    flat = np.full((40, 40, 3), 0.3, np.float32)          # nothing for sep to find
    img = AstroImage(flat, is_linear=False)
    starless, stars = split_stars(img)
    assert np.allclose(starless.data, flat)
    assert np.allclose(stars.data, 0.0)


def test_mono_image_splits():
    data = _scene()
    img = AstroImage(data, is_linear=False)               # 2-D
    starless, stars = split_stars(img)
    recon = 1.0 - (1.0 - starless.data) * (1.0 - stars.data)
    assert np.abs(recon - img.data).max() < 1e-4


def test_star_mask_covers_stars_and_widens_with_scale():
    # star_mask() is the public feathered star-neighbourhood mask the free
    # Green-Fringe path de-greens inside. It must be ~1 on the star, ~0 on empty
    # sky, and a larger scale must extend the covered region past the core.
    from nocturne.core.starless import star_mask
    h = w = 100
    yy, xx = np.mgrid[0:h, 0:w]
    r2 = (yy - 50) ** 2 + (xx - 50) ** 2
    data = np.clip(0.08 + 0.7 * np.exp(-r2 / (2 * 1.6 ** 2)), 0, 1).astype(np.float32)
    img = AstroImage(np.stack([data] * 3, axis=2), is_linear=False)
    narrow = star_mask(img, mask_scale=1.0)
    wide = star_mask(img, mask_scale=2.5)
    assert narrow[50, 50] > 0.8                            # covers the star core (feather softens peak)
    assert narrow[5, 5] < 0.05                             # spares empty sky
    assert (wide > 0.5).sum() > (narrow > 0.5).sum() * 1.5  # wider mask, larger region
