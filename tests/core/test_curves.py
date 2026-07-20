import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.curves import build_lut, apply_curve, gentle_s_points, sanitize_points

IDENTITY = [(0.0, 0.0), (1.0, 1.0)]


def test_identity_lut_is_ramp():
    lut = build_lut(IDENTITY, n=1024)
    assert lut.shape == (1024,)
    assert np.allclose(lut, np.linspace(0.0, 1.0, 1024), atol=1e-4)


def test_lut_is_monotonic_for_reasonable_points():
    lut = build_lut([(0.0, 0.0), (0.3, 0.15), (0.6, 0.8), (1.0, 1.0)])
    assert np.all(np.diff(lut) >= -1e-6)          # never decreases
    assert lut.min() >= 0.0 and lut.max() <= 1.0


def test_build_lut_handles_duplicate_x_without_nan_or_inf():
    # a hand-edited batch recipe could contain coincident x control points;
    # build_lut must not divide by a zero h and produce nan/inf.
    pts = [(0.0, 0.0), (0.5, 0.3), (0.5, 0.7), (1.0, 1.0)]
    lut = build_lut(pts)
    assert np.all(np.isfinite(lut))
    assert np.all(np.diff(lut) >= -1e-6)          # never decreases
    assert lut.min() >= 0.0 and lut.max() <= 1.0


def test_build_lut_handles_near_duplicate_x_without_nan_or_inf():
    pts = [(0.0, 0.0), (0.5, 0.3), (0.5 + 1e-12, 0.7), (1.0, 1.0)]
    lut = build_lut(pts)
    assert np.all(np.isfinite(lut))
    assert np.all(np.diff(lut) >= -1e-6)
    assert lut.min() >= 0.0 and lut.max() <= 1.0


def test_build_lut_handles_duplicate_x_at_left_edge_without_nan_or_inf():
    # a duplicate at the very first x is the case that reliably corrupts the
    # whole LUT with nan (m[0] = delta[0] = inf/nan when h[0] == 0).
    pts = [(0.0, 0.0), (0.0, 0.3), (0.5, 0.5), (1.0, 1.0)]
    lut = build_lut(pts)
    assert np.all(np.isfinite(lut))
    assert np.all(np.diff(lut) >= -1e-6)
    assert lut.min() >= 0.0 and lut.max() <= 1.0


def test_apply_identity_is_noop():
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((32, 32, 3)).astype(np.float32), is_linear=False)
    out = apply_curve(img, IDENTITY).data
    assert np.allclose(out, img.data, atol=1e-4)


def test_lifted_midtone_raises_mids_keeps_endpoints():
    # a flat mid-grey field lifts; pure black / pure white pixels stay put
    data = np.full((16, 16, 3), 0.5, np.float32)
    data[0, 0] = 0.0
    data[0, 1] = 1.0
    out = apply_curve(AstroImage(data), [(0.0, 0.0), (0.5, 0.68), (1.0, 1.0)]).data
    assert out[8, 8].mean() > 0.6            # midtone lifted
    assert np.allclose(out[0, 0], 0.0, atol=1e-4)   # black endpoint pinned
    assert np.allclose(out[0, 1], 1.0, atol=1e-4)   # white endpoint pinned


def test_output_range_and_dtype():
    rng = np.random.default_rng(1)
    img = AstroImage(rng.random((24, 24, 3)).astype(np.float32))
    out = apply_curve(img, [(0.0, 0.0), (0.4, 0.1), (0.7, 0.9), (1.0, 1.0)])
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def test_preserves_is_linear_and_metadata():
    img = AstroImage(np.full((8, 8, 3), 0.5, np.float32),
                     is_linear=False, metadata={"k": 1})
    out = apply_curve(img, [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_greyscale_path():
    data = np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8)
    out = apply_curve(AstroImage(data), [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    assert out.data.ndim == 2
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def _bg_image():
    # 80% background at 0.15, rest brighter -> 10th percentile ~ 0.15
    lum = np.full((100, 100), 0.15, np.float32)
    lum[:, 80:] = 0.6
    return np.repeat(lum[:, :, None], 3, axis=2)


def test_gentle_s_points_shape_and_pin():
    pts = gentle_s_points(_bg_image())
    xs = [p[0] for p in pts]
    assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0)   # corners present
    assert xs == sorted(xs) and len(set(xs)) == len(xs)     # strictly increasing x
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in pts)
    # background (~0.15) is pinned: the curve does not lift it
    lut = build_lut(pts)
    bg_out = lut[int(0.15 * (len(lut) - 1))]
    assert abs(bg_out - 0.15) < 0.03


def test_gentle_s_adds_midtone_contrast():
    lut = build_lut(gentle_s_points(_bg_image()))
    lo, hi = lut[int(0.45 * 1023)], lut[int(0.75 * 1023)]
    slope = (hi - lo) / (0.75 - 0.45)
    assert slope > 1.0        # steeper than linear through the midtones


def test_sanitize_points_forces_corners_and_min_gap():
    pts = sanitize_points([(0.3, 0.2), (0.305, 0.25), (0.6, 0.4)])
    xs = [p[0] for p in pts]
    assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0)
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    assert len(pts) == 4          # 0.305 was too close to 0.3 -> dropped, corners kept


def test_sanitize_points_is_idempotent():
    once = sanitize_points([(0.3, 0.2), (0.6, 0.4), (0.9995, 0.9)])
    twice = sanitize_points(once)
    assert once == twice
