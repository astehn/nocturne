import numpy as np
from nocturne.stacking.drizzle_stack import (
    build_pixmap,
    drizzle_clipped,
    drizzle_integrate,
    DRIZZLE_SCALE,
)


def test_pixmap_identity_scales_by_factor():
    pm = build_pixmap(np.eye(3), (3, 4), scale=2)          # H=3, W=4
    assert pm.shape == (3, 4, 2)
    assert np.allclose(pm[0, 0], [0, 0])                    # input (0,0) -> output (0,0)
    assert np.allclose(pm[2, 3], [6, 4])                    # input (x=3,y=2) -> (6,4)


def test_pixmap_applies_shift_then_scale():
    m = np.array([[1, 0, 1.5], [0, 1, -0.5], [0, 0, 1]])    # +1.5 in x, -0.5 in y
    pm = build_pixmap(m, (2, 2), scale=1)
    assert np.allclose(pm[0, 0], [1.5, -0.5])              # (x=0,y=0) -> (1.5,-0.5)
    assert np.allclose(pm[1, 1], [2.5, 0.5])


def test_drizzle_constant_field_is_preserved():
    # N identical constant frames (no shift) -> output constant at the input level
    frame = np.full((16, 16, 1), 0.4, np.float32)
    items = [(frame, np.eye(3), None) for _ in range(6)]
    out = drizzle_integrate(items, (16, 16), 1)
    assert out.shape == (32, 32, 1)
    interior = out[8:24, 8:24, 0]                          # away from edges
    assert np.allclose(interior, 0.4, atol=0.05)           # weight-normalized average


def test_drizzle_places_a_shifted_star():
    # a single bright pixel, dithered by sub-pixel shifts, lands near 2×(center)
    frames = []
    for dx, dy in [(0, 0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5)]:
        f = np.zeros((16, 16, 1), np.float32); f[8, 8, 0] = 1.0
        m = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], float)
        frames.append((f, m, None))
    out = drizzle_integrate(frames, (16, 16), 1)[..., 0]
    peak = np.unravel_index(np.argmax(out), out.shape)
    assert abs(peak[0] - 16) <= 2 and abs(peak[1] - 16) <= 2   # ~2×(8,8)


def test_drizzle_clipped_rejects_an_outlier():
    # N=11 (10 good + 1 outlier): single-pass sigma-clip only flags a lone
    # outlier past the sqrt(N-1) bound, which at kappa=2.5 needs N>=~8.
    base = np.full((16, 16, 1), 0.3, np.float32)
    good = [(base.copy(), np.eye(3)) for _ in range(10)]
    bad = base.copy(); bad[8, 8, 0] = 1.0                  # a satellite-like hot pixel
    frames = good + [(bad, np.eye(3))]
    make = lambda: list(frames)

    masked, _ = drizzle_clipped(make, (16, 16), 1)
    assert not np.isnan(masked).any()                      # fillval=0.0, no NaNs
    masked = masked[..., 0]

    # Genuine rejection, not averaging dilution: the masked result at the outlier
    # is measurably lower than an *unmasked* drizzle-average of the same frames.
    unmasked = drizzle_integrate([(d, m, None) for (d, m) in frames], (16, 16), 1)[..., 0]
    assert masked[16, 16] < unmasked[16, 16] - 0.02        # the mask removed the outlier
    assert masked[16, 16] < 0.5                            # not lifted toward 1.0


# --- end to end through run_stack (2026-08-31 un-shelving) -------------------

def test_run_stack_drizzle_produces_a_2x_master(tmp_path):
    """The wiring, not the maths: a drizzle stack must come out on the 2x grid
    and go through the same normalise/grade/autocrop path as any other method."""
    import numpy as np
    from nocturne.stacking.stacker import StackOptions, run_stack
    from tests.stacking.synthetic import make_star_field, write_cfa_fits

    base = make_star_field(shape=(96, 96), n_stars=25, seed=4)
    rng = np.random.default_rng(0)
    paths = []
    for i in range(8):
        img = np.roll(base, i % 3, axis=1)
        img = np.clip(img + rng.normal(0, 0.01, img.shape), 0, 1).astype(np.float32)
        p = tmp_path / f"sub_{i:03d}.fit"
        write_cfa_fits(str(p), img)
        paths.append(str(p))

    out = tmp_path / "drz.fits"
    res = run_stack(StackOptions("drizzle", 2.5, paths, str(out), autocrop=False))
    assert res.image.data.shape[0] > 96, (
        f"not on the 2x grid: {res.image.data.shape}")
    assert np.isfinite(res.image.data).all(), "NaNs in the drizzle master"
    assert out.exists()


def test_drizzle_frames_are_sky_normalised_like_every_other_method(tmp_path):
    """The reason drizzle was shelved in 2026-07 and the reason it is back.

    The 2026-07 branch fed RAW frames, because per-frame sky normalisation did
    not exist until d1d842e (2026-08-04) — eleven days later. Unnormalised sky
    turns every coverage boundary into a step in background level, which normal
    stacking hides behind interpolation and drizzle, interpolating nothing,
    draws as a patchwork. If drizzle ever stops going through normalize_to, that
    comes straight back.
    """
    import inspect
    from nocturne.stacking import stacker
    src = inspect.getsource(stacker.run_stack)
    body = src.split("def drizzle_items()")[1].split("if opts.method ==")[0]
    assert "normalize_to" in body, (
        "drizzle no longer normalises each frame's sky — this is what put the "
        "patchwork in the 2026-07 masters")


def test_drizzle_is_handed_unwarped_frames(tmp_path):
    """Drizzle does its own resampling — that is the point. Handing it an
    already-warped frame interpolates twice and throws away the very resolution
    it exists to recover."""
    import inspect
    from nocturne.stacking import stacker
    src = inspect.getsource(stacker.run_stack)
    body = src.split("def drizzle_items()")[1].split("if opts.method ==")[0]
    assert "warp_with_validity" not in body and "warp_to" not in body, (
        "drizzle is being fed pre-warped frames")
