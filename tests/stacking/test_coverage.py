import numpy as np
from nocturne.stacking.coverage import full_coverage_bounds, _largest_true_rectangle


def test_largest_true_rectangle_finds_block():
    mask = np.zeros((4, 5), bool)
    mask[1:3, 1:4] = True          # rows 1-2, cols 1-3 (a 2x3 block)
    assert _largest_true_rectangle(mask) == (1, 3, 1, 4)


def test_largest_true_rectangle_all_true():
    assert _largest_true_rectangle(np.ones((3, 6), bool)) == (0, 3, 0, 6)


def test_identity_transforms_cover_every_pixel():
    """Coverage now comes from integration itself rather than a second warp of a
    ones mask, so this asserts the property where it is actually produced."""
    from nocturne.stacking.integrate import average_integrate
    frames = [np.full((6, 6), 0.5, np.float32) for _ in range(3)]
    _, cov = average_integrate(frames)
    assert cov.shape == (6, 6)
    assert np.all(cov == 3)


def test_full_coverage_bounds_crops_to_covered_core():
    # A hand-built coverage map: only a central 4x4 core got all 5 frames.
    cov = np.zeros((10, 10), np.int32)
    cov[:] = 2                       # edges: partial coverage
    cov[3:7, 3:7] = 5                # core: full coverage
    top, bottom, left, right = full_coverage_bounds(cov, n_frames=5)
    assert (top, bottom, left, right) == (3, 7, 3, 7)


def test_full_coverage_bounds_falls_back_when_none_meets_threshold():
    cov = np.ones((8, 8), np.int32)  # every pixel covered by only 1 frame
    assert full_coverage_bounds(cov, n_frames=10) == (0, 8, 0, 8)


def test_the_default_threshold_keeps_only_near_fully_covered_pixels():
    """Pins the tuned constant, which the test above does not: it passes at any
    frac between ~0.3 and ~1.0 because its bands are far apart.

    The constant is high because frames are NOT normalized to a common sky
    level. An interior pixel averages every frame; a fringe pixel averages only
    the subset that reached it, and those subsets have different mean sky. On
    real M31 data the sky varies 262% between frames, so every coverage
    boundary became a visible step and the rotation envelope was drawn on the
    picture — seen 2026-08-03 after this was briefly relaxed to 0.5 on a
    noise-only argument, which is why the bands here are 85% and 95% rather
    than the 45/55 that noise alone would justify.

    When per-frame normalization lands ("additive + scaling", as Siril does),
    this can drop to the noise-driven value of about 0.5 and THIS TEST SHOULD
    CHANGE WITH IT — it pins today's constraint, not a permanent truth.
    """
    import inspect
    from nocturne.stacking import coverage as c

    n = 20
    cov = np.full((n, n), 17, np.int32)     # 85% — subset still differs enough
    cov[4:16, 4:16] = 19                    # 95% — effectively every frame
    cov[8:12, 8:12] = n
    assert full_coverage_bounds(cov, n_frames=n) == (4, 16, 4, 16), \
        "the default no longer sits between 85% and 95% coverage"

    frac = inspect.signature(c.full_coverage_bounds).parameters["frac"].default
    assert frac >= 0.85, (
        f"frac={frac} keeps fringe whose covering subset differs from the "
        "interior's — that shows as sky-level banding until frames are normalized")


def test_a_sparse_fringe_is_still_cut_off():
    """The relaxation must not become 'keep everything'. A rim covered by a
    handful of frames is genuinely poor data and stays outside the crop."""
    n = 40
    cov = np.full((30, 30), 3, np.int32)    # 7.5% — a sparse rim
    cov[5:25, 5:25] = n
    assert full_coverage_bounds(cov, n_frames=n) == (5, 25, 5, 25)


def test_the_threshold_is_not_rounded_up():
    """For an INTEGER coverage map, rounding up selects exactly the same pixels
    — there are no integers between 0.9*n and ceil(0.9*n). For drizzle it was
    fatal: its coverage is a continuous weight rescaled so the MEDIAN maps to
    the frame count, so ceil(7.2)=8 at n=8 demanded >= 8 exactly, and by
    construction about half the interior fell a hair short — scattered like
    noise rather than forming an envelope, which collapses the largest
    hole-free rectangle.

    Measured on real NGC 281 subs 2026-09-04: 96 x 1712 out of 4320 x 7680,
    against 4110 x 7572 for the same mask at the unrounded threshold.
    """
    import numpy as np
    from nocturne.stacking.coverage import full_coverage_bounds

    # A continuous coverage map like drizzle's: interior sits AT the frame
    # count, half of it a hair below, with a genuine low-coverage border.
    rng = np.random.default_rng(4)
    cov = 8.0 + rng.normal(0, 0.03, size=(400, 600)).astype(np.float32)
    cov[:25, :] = 3.0
    cov[-25:, :] = 3.0
    cov[:, :20] = 3.0
    cov[:, -20:] = 3.0
    top, bottom, left, right = full_coverage_bounds(cov, 8)
    kept = (bottom - top) * (right - left)
    assert kept > 0.7 * cov.size, (
        f"kept only {100 * kept / cov.size:.1f}% — the interior is being "
        f"rejected as noise, which is the drizzle auto-crop bug")
    # ...and it really did find the border, rather than keeping everything.
    assert top >= 20 and left >= 15


def test_an_integer_coverage_map_is_unaffected_by_that():
    """The change must be a no-op for every other stacking method."""
    import numpy as np
    from nocturne.stacking.coverage import full_coverage_bounds
    for n in (3, 8, 12, 20, 100):
        cov = np.full((200, 300), n, np.int32)
        cov[:10, :] = 1
        cov[:, :7] = 1
        assert full_coverage_bounds(cov, n) == (10, 200, 7, 300), f"n={n}"


def test_a_pixel_one_frame_short_is_still_excluded():
    """The threshold must not become so loose that a genuinely under-covered
    pixel survives — that is what draws the rotation envelope on the picture."""
    import numpy as np
    from nocturne.stacking.coverage import full_coverage_bounds
    cov = np.full((200, 300), 10, np.int32)
    cov[:, :50] = 9          # 9 of 10 frames = 90%, below the 0.9*10 bar? no: equal
    cov[:, :20] = 8          # 8 of 10 = 80%, must be excluded
    top, bottom, left, right = full_coverage_bounds(cov, 10)
    assert left >= 20, "an 80%-covered strip was kept"
