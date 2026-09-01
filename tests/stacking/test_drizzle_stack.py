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


# --- a 2x master describes its own scale (found on real data 2026-08-31) -----

def test_a_drizzle_master_halves_its_pixel_size():
    """A 2x master's pixel covers HALF the sky its subs' pixels did. Copying the
    reference frame's XPIXSZ verbatim tells the solver the field is twice as
    wide as it is — on a real 314-frame M 16 drizzle, ASTAP searched a "4.27 deg
    square search window" for a field about half that and reported "No solution
    found", which cost SPCC its photometric calibration."""
    from nocturne.stacking.stacker import master_header, master_metadata
    ref = {"pixel_size": 2.9, "focal_length": 160.0, "target": "M 16",
           "solve_cards": {"XPIXSZ": 2.9, "YPIXSZ": 2.9, "FOCALLEN": 160.0,
                           "CD1_1": 0.001, "RA": 274.7}}
    h = master_header(ref, 314, 3140.0, trimmed=False, scale=2)
    assert h["XPIXSZ"] == 1.45 and h["YPIXSZ"] == 1.45
    assert h["FOCALLEN"] == 160.0, "focal length is unchanged — the optics did not move"
    assert h["CD1_1"] == 0.0005, "the WCS scale must halve too"
    assert h["RA"] == 274.7, "pointing is unchanged"
    m = master_metadata(ref, 314, 3140.0, 7680, 4320, scale=2)
    assert m["pixel_size"] == 1.45


def test_a_normal_master_is_left_exactly_as_it_was():
    """Every non-drizzle stack goes through the same code. Registration is a
    rigid transform, so the reference's optics still describe the master."""
    from nocturne.stacking.stacker import master_header, master_metadata
    ref = {"pixel_size": 2.9, "solve_cards": {"XPIXSZ": 2.9, "CD1_1": 0.001}}
    assert master_header(ref, 10, 100.0)["XPIXSZ"] == 2.9
    assert master_metadata(ref, 10, 100.0, 3840, 2160)["pixel_size"] == 2.9


def test_the_estimate_is_in_the_right_order_of_magnitude():
    """It only has to answer "minutes or an hour". Measured: 60 frames of
    3840x2160 took 220 s."""
    from nocturne.stacking.drizzle_stack import estimate_megabytes, estimate_seconds
    assert 150 < estimate_seconds(60, (2160, 3840)) < 320
    assert estimate_seconds(600, (2160, 3840)) > 9 * estimate_seconds(60, (2160, 3840)) * 0.9
    assert 350 < estimate_megabytes((2160, 3840)) < 450     # a real one was 398 MB


def test_frames_that_did_not_cover_a_pixel_do_not_count_as_zero_there():
    """THE edge bug. Andreas' first real drizzle stack showed coloured streaks
    along the rotation envelope that the normal stack of the same subs, framed
    the same way, did not.

    warp fills outside the source with ZERO, and zero is a legitimate pixel
    value — register.warp_with_validity exists in the normal path for exactly
    this reason. Drizzle's pass 1 had no mask, so a pixel seen by half the
    frames had its mean halved and its variance inflated, and pass 2 then
    rejected real data against corrupted statistics. Per channel differently,
    hence the colour.

    Constructed so the failure is arithmetic rather than aesthetic: half the
    frames are shifted far enough that they do not reach the left edge at all.
    """
    import numpy as np
    from nocturne.stacking.drizzle_stack import _warp_to_grid

    data = np.full((32, 32, 1), 0.5, np.float64)
    shifted = np.eye(3)
    # Far enough to leave a 64-wide output entirely. +40 does NOT: the inverse
    # maps output columns 40..63 back onto input 0..23, so 768 pixels are still
    # legitimately covered. The first version of this test asserted otherwise
    # and failed against correct code.
    shifted[0, 2] = 200.0
    warped, valid = _warp_to_grid(data, shifted, (64, 64))
    assert not valid.any(), "a frame moved right off the grid still claims coverage"

    warped, valid = _warp_to_grid(data, np.eye(3), (64, 64))
    assert valid.any(), "an aligned frame covers nothing"
    # Where the frame does NOT reach, warp filled zeros — which must not be
    # mistaken for real dark sky.
    assert (warped[~valid] == 0).all()
    assert np.allclose(warped[valid], 0.5), "covered pixels lost their value"


def test_a_thinly_covered_region_is_not_rejected_into_nothing():
    """End to end, and calibrated so the bug actually fires.

    A first version used half-covered pixels and PASSED against the broken code.
    The reason is worth keeping: the corrupted mean only changes what pass 2
    REJECTS, and rejection needs |value - mean| > kappa*std. For a pixel covered
    by fraction f, the unmasked mean is f*V and its std V*sqrt(f(1-f)), so the
    test only bites when (1-f)/f > kappa^2 — below about 14% coverage at
    kappa 2.5. At f = 0.5 the wrong mean is not wrong ENOUGH, and the test
    proved nothing.

    So: one frame in twelve reaches the far strip. Unmasked, its mean there is
    V/12 with a std that makes the real data look like a 12-sigma outlier — it
    is rejected outright and the strip comes out as fill, which is what drew
    streaks along Andreas' rotation envelope.
    """
    import numpy as np
    from nocturne.stacking.drizzle_stack import drizzle_clipped

    level = 0.4
    full = np.full((32, 32, 1), level, np.float32)
    frames = [(full.copy(), np.eye(3)) for _ in range(11)]
    off = np.eye(3)
    off[0, 2] = 34.0          # this one alone reaches beyond the others
    frames.append((full.copy(), off))

    out, _ = drizzle_clipped(lambda: list(frames), (32, 32), 1)
    strip = out[20:44, 40:60, 0]           # only the twelfth frame covers this
    live = strip[strip > 0]
    assert live.size > 50, (
        f"the thinly covered strip came out empty ({live.size} live pixels) — "
        f"its data was rejected against statistics that counted the eleven "
        f"frames which never saw it")
    assert abs(float(np.median(live)) - level) < 0.1 * level, (
        f"level came out {np.median(live):.4f} instead of {level}")


def test_the_progress_steps_add_up():
    """A 2,037-frame run spent hours reporting "Step 3 of 2". Drizzle walks the
    frames twice — measure, then drizzle — so it has three phases like
    sigma-clip, and the count has to know that."""
    import re
    from unittest.mock import patch
    import numpy as np
    from nocturne.stacking.stacker import StackOptions, run_stack
    from tests.stacking.synthetic import make_star_field, write_cfa_fits

    def labels_for(method, tmp):
        base = make_star_field(shape=(64, 64), n_stars=20, seed=2)
        rng = np.random.default_rng(0)
        paths = []
        for i in range(6):
            img = np.clip(base + rng.normal(0, 0.01, base.shape), 0, 1).astype(np.float32)
            p = tmp / f"{method}_{i:03d}.fit"
            write_cfa_fits(str(p), img)
            paths.append(str(p))
        seen = []
        run_stack(StackOptions(method, 2.5, paths, str(tmp / f"{method}.fits"),
                               autocrop=False),
                  on_progress=lambda i, n, label: seen.append(label))
        return seen

    import tempfile
    import pathlib
    with tempfile.TemporaryDirectory() as d:
        for method in ("drizzle", "sigma_clip", "average"):
            labels = labels_for(method, pathlib.Path(d))
            pairs = {(int(m.group(1)), int(m.group(2)))
                     for lab in labels
                     if (m := re.search(r"Step (\d+) of (\d+)", lab))}
            assert pairs, f"{method} reported no numbered steps"
            for step, total in pairs:
                assert step <= total, (
                    f"{method} reported 'Step {step} of {total}'")
