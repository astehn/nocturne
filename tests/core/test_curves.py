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


def test_sanitize_points_drops_points_closer_than_the_min_gap():
    """Corners are no longer forced — see the endpoint tests below — but the
    spacing rule still holds, because build_lut needs strictly increasing x."""
    pts = sanitize_points([(0.3, 0.2), (0.305, 0.25), (0.6, 0.4)])
    xs = [p[0] for p in pts]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    assert len(pts) == 2, "0.305 was too close to 0.3 and should have gone"
    assert pts[0] == (0.3, 0.2), "the caller's endpoint must survive"


def test_sanitize_points_is_idempotent():
    once = sanitize_points([(0.3, 0.2), (0.6, 0.4), (0.9995, 0.9)])
    twice = sanitize_points(once)
    assert once == twice


# --- endpoints: black point / white point (2026-08-17) -----------------------
# The corners used to be pinned at (0,0) and (1,1), which made setting a black
# or white point impossible — the single most common curves move. Unpinning them
# exposed that build_lut EXTRAPOLATES the Hermite polynomial outside the control
# points instead of holding the end values.

def test_below_the_first_point_holds_its_value_instead_of_extrapolating():
    """A black point lifted to (0.3, 0.5) must map everything darker to 0.5.
    The polynomial ran on regardless and gave 0.29 at x=0 — a *darker* output
    than the black point itself, so lifting the blacks crushed them instead.
    The two cases where extrapolation happened to leave [0,1] were clipped and
    looked correct, which is why this hid."""
    lut = build_lut([(0.3, 0.5), (1.0, 1.0)], n=101)
    below = lut[:30]
    assert np.allclose(below, 0.5, atol=1e-6), f"got {below.min()}..{below.max()}"


def test_above_the_last_point_holds_its_value_instead_of_extrapolating():
    """A white point pulled down to (0.7, 0.8) must map everything brighter to
    0.8. It kept climbing to 1.0, so the highlight roll-off did nothing."""
    lut = build_lut([(0.0, 0.0), (0.7, 0.8)], n=101)
    above = lut[71:]
    assert np.allclose(above, 0.8, atol=1e-6), f"got {above.min()}..{above.max()}"


def test_a_black_point_clips_the_shadows_to_zero():
    """The ordinary black-point move: drag the low endpoint right. Everything at
    or below that input becomes pure black."""
    lut = build_lut([(0.25, 0.0), (1.0, 1.0)], n=101)
    assert np.allclose(lut[:26], 0.0, atol=1e-6)
    assert lut[60] > 0.0, "midtones must still pass"


def test_sanitize_keeps_endpoints_the_user_moved():
    """sanitize_points used to force (0,0) and (1,1) onto every point list, so
    an endpoint drag was discarded the moment it was committed."""
    pts = sanitize_points([(0.2, 0.05), (0.5, 0.5), (0.9, 0.95)])
    assert pts[0] == (0.2, 0.05), f"first endpoint rewritten to {pts[0]}"
    assert pts[-1] == (0.9, 0.95), f"last endpoint rewritten to {pts[-1]}"


def test_sanitize_still_sorts_clamps_and_spaces_interior_points():
    """Unpinning the corners must not lose the guarantees build_lut relies on:
    sorted, inside [0,1], and no two points closer than the minimum gap."""
    pts = sanitize_points([(0.9, 0.9), (0.5, 0.5), (0.505, 0.6), (-0.2, 0.1), (1.4, 2.0)])
    xs = [x for x, _ in pts]
    assert xs == sorted(xs), "not sorted"
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in pts), "outside [0,1]"
    assert all(b - a > 0 for a, b in zip(xs, xs[1:])), "coincident x survived"


def test_identity_is_unchanged_by_the_endpoint_work():
    """The default curve must still be a no-op — this is the regression that
    would silently alter every image that never touches Curves."""
    lut = build_lut(IDENTITY, n=256)
    assert np.allclose(lut, np.linspace(0, 1, 256), atol=1e-6)


# ------------------------------------------------- background-aware presets

def _sky(level, shape=(64, 64, 3), signal=None):
    """An image whose sky sits at `level`, with optional brighter signal."""
    import numpy as np
    rng = np.random.default_rng(0)
    a = np.full(shape, level, np.float32) + rng.normal(0, 0.004, shape).astype(np.float32)
    if signal:
        lo, hi, frac = signal
        n = int(a.shape[0] * frac)
        a[:n] = np.linspace(lo, hi, n)[:, None, None]
    return np.clip(a, 0, 1)


def _apply(pts, x):
    """What the curve maps input x to."""
    import numpy as np
    from nocturne.core.curves import build_lut
    lut = build_lut(pts)
    return float(lut[int(round(np.clip(x, 0, 1) * (len(lut) - 1)))])


def test_every_preset_finds_the_sky_rather_than_a_fixed_position():
    """The presets must be measured from the image, never from constants.

    Colour Balance learned this the hard way: its band presets used absolute
    values, and on M 31 — whose stretched sky sits at 0.256 — they selected 87%
    of the frame, the inverse of what was intended. A curve preset with fixed
    point positions has exactly the same failure.

    So: the SAME preset on two images with different sky levels must put its
    anchor in different places.
    """
    from nocturne.core.curves import lift_faint_points
    dark = lift_faint_points(_sky(0.08))
    bright = lift_faint_points(_sky(0.32))
    anchor_dark = min(x for x, _ in dark if x > 0.001)
    anchor_bright = min(x for x, _ in bright if x > 0.001)
    assert anchor_bright > anchor_dark + 0.1, (anchor_dark, anchor_bright)


def test_lift_faint_detail_raises_just_above_the_sky_and_pins_the_sky():
    """The point of the preset: outer nebulosity comes up, the background does
    NOT grey out. Pinning the sky is what separates this from 'brighten'."""
    from nocturne.core.curves import lift_faint_points
    bg = 0.15
    pts = lift_faint_points(_sky(bg))
    assert abs(_apply(pts, bg) - bg) < 0.01, "the sky must stay where it is"
    just_above = bg + (1.0 - bg) * 0.15
    assert _apply(pts, just_above) > just_above + 0.01, "faint detail must lift"


def test_deepen_sky_lowers_the_background_without_crushing_faint_signal():
    """The opposite move. It must darken the sky but leave the signal just above
    it recoverable — a curve that flattens both is just a black-point slide."""
    from nocturne.core.curves import deepen_sky_points
    bg = 0.20
    pts = deepen_sky_points(_sky(bg))
    assert _apply(pts, bg) < bg - 0.005, "the sky must come down"
    just_above = bg + (1.0 - bg) * 0.25
    assert _apply(pts, just_above) > _apply(pts, bg) + 0.05, (
        "faint signal must stay clearly above the darkened sky")


def test_tame_highlights_pulls_the_top_down_and_leaves_midtones_alone():
    from nocturne.core.curves import tame_highlights_points
    pts = tame_highlights_points(_sky(0.12))
    assert _apply(pts, 0.97) < 0.97 - 0.01, "the top end must roll off"
    assert abs(_apply(pts, 0.5) - 0.5) < 0.06, "midtones should barely move"


def test_stronger_contrast_is_stronger_than_the_gentle_one():
    """Not merely different — measurably more S."""
    from nocturne.core.curves import gentle_s_points, strong_s_points
    data = _sky(0.12)
    g, s = gentle_s_points(data), strong_s_points(data)
    lo, hi = 0.30, 0.75
    gentle_spread = _apply(g, hi) - _apply(g, lo)
    strong_spread = _apply(s, hi) - _apply(s, lo)
    assert strong_spread > gentle_spread + 0.02, (gentle_spread, strong_spread)


def test_no_preset_inverts_or_overshoots():
    """A tone curve must stay monotone and inside [0,1]. build_lut uses
    monotone-cubic interpolation for this, but a preset can still hand it points
    that ask for the impossible."""
    import numpy as np
    from nocturne.core.curves import (build_lut, deepen_sky_points,
                                      gentle_s_points, lift_faint_points,
                                      strong_s_points, tame_highlights_points)
    for fn in (gentle_s_points, strong_s_points, lift_faint_points,
               deepen_sky_points, tame_highlights_points):
        for bg in (0.05, 0.15, 0.30, 0.45):
            lut = build_lut(fn(_sky(bg)))
            assert np.all(np.diff(lut) >= -1e-6), f"{fn.__name__} inverts at bg={bg}"
            assert lut.min() >= -1e-6 and lut.max() <= 1 + 1e-6, fn.__name__


def test_tame_highlights_never_brightens_anything():
    """It rolls the top off. It must never LIFT a value, anywhere.

    Caught on real data, not by the synthetic tests above: the roll-off used to
    start at a fixed 80% of the span, and on the M 31 mosaic — whose bright end
    sits at 0.773, below that — the image's highlights never reached the part of
    the curve meant to tame them, while the monotone spline bulged slightly
    ABOVE the identity line on the way there. Measured +0.0098 where it should
    have been negative.

    So the preset has to find where the image's highlights actually are, the way
    it already finds the sky.
    """
    import numpy as np
    from nocturne.core.curves import build_lut, tame_highlights_points
    for bg in (0.05, 0.15, 0.30):
        for top in (0.55, 0.75, 0.95):
            data = _sky(bg)
            data[:8] = top                       # where this image's highlights sit
            lut = build_lut(tame_highlights_points(data))
            xs = np.linspace(0, 1, len(lut))
            # Half an 8-bit level. Not an arbitrary softening: monotone-cubic
            # interpolation guarantees no INVERSION, not that a curve stays
            # below its own chord, so an exact zero is unattainable here. The
            # anchors in the preset bring the worst case to 0.40 of a level,
            # which cannot survive quantisation to any output format.
            assert np.all(lut <= xs + 1.0 / 512), (
                f"tame highlights brightened something at bg={bg}, top={top}: "
                f"max lift {float((lut - xs).max()) * 255:+.2f} 8-bit levels")


def test_tame_highlights_actually_reaches_this_image_s_highlights():
    """Not merely harmless — it has to DO something where the picture is bright."""
    import numpy as np
    from nocturne.core.curves import build_lut, tame_highlights_points
    data = _sky(0.15)
    data[:8] = 0.75                              # a modest bright end, as on M 31
    lut = build_lut(tame_highlights_points(data))
    at = float(lut[int(0.75 * (len(lut) - 1))])
    assert at < 0.75 - 0.005, f"highlights at 0.75 barely moved: {at:.4f}"


# --- the curve matrix: channel x hue range -----------------------------------
#
# Andreas asked for per-channel Hue/Saturation/Luminance on 2026-09-04 and sent
# AstroWizard screenshots the next morning showing the shape he meant: a curves
# dialog with a CHANNEL selector (RGB/R/G/B/S) and a TARGET hue range, so
# "S + Reds" is a saturation curve applied only to the reds. See
# docs/HSL_DESIGN_QUESTION.md.

import colorsys

from nocturne.core.curves import (CURVE_CHANNELS, CURVE_RANGES, active_curves,
                                  apply_curve, apply_curves, curve_key,
                                  normalize_curves, range_weight)

_IDENT = [(0.0, 0.0), (1.0, 1.0)]
_BOOST = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]


def _hue_strip(hues, value=0.8, sat=1.0):
    import numpy as np
    return np.array([[colorsys.hsv_to_rgb(h, sat, value) for h in hues]], np.float32)


def _img(data):
    from nocturne.core.image import AstroImage
    return AstroImage(data, is_linear=False, metadata={})


def test_a_bare_list_of_points_still_means_what_it_always_meant():
    """Every project and recipe written before 2026-09-05 stores this step as a
    bare list. A saved recipe that silently stopped applying its curve is the
    worst kind of regression — the batch still succeeds and only the pictures
    are wrong."""
    import numpy as np
    img = _img(np.random.default_rng(0).random((6, 6, 3)).astype(np.float32))
    assert np.allclose(apply_curves(img, _BOOST).data, apply_curve(img, _BOOST).data)


def test_the_six_ranges_are_a_partition_of_unity():
    """A curve applied identically to all six ranges must equal the same curve
    applied to "all", or the range boundaries show as seams. That holds only if
    the weights sum to exactly 1 at every hue."""
    import numpy as np
    strip = _hue_strip(np.linspace(0, 1, 37, endpoint=False))
    total = sum(range_weight(strip, r) for r in CURVE_RANGES if r != "all")
    assert np.allclose(total, 1.0, atol=1e-5), (total.min(), total.max())


def test_a_grey_pixel_belongs_to_no_hue_range():
    """Without weighting by saturation, a hue-targeted curve would grab the
    whole background — which on an astro frame is most of the picture — and
    "Reds" would behave like "All colours" on everything but a bright nebula."""
    import numpy as np
    grey = np.full((4, 4, 3), 0.4, np.float32)
    for r in CURVE_RANGES:
        if r == "all":
            continue
        assert float(range_weight(grey, r).max()) == 0.0, r


def test_a_targeted_curve_leaves_other_hues_alone():
    import numpy as np
    strip = _hue_strip([0.0, 1 / 3, 2 / 3])          # pure red, green, blue
    out = apply_curves(_img(strip), {curve_key("rgb", "reds"): _BOOST}).data
    assert not np.allclose(out[0, 0], strip[0, 0]), "the red pixel should move"
    assert np.allclose(out[0, 1], strip[0, 1], atol=1e-6), "green must not"
    assert np.allclose(out[0, 2], strip[0, 2], atol=1e-6), "blue must not"


def test_the_rgb_channel_preserves_hue_and_a_single_channel_does_not():
    """Two deliberately different behaviours in one dialog. RGB rescales the
    whole pixel by the luminance ratio, as it always has; moving R alone is how
    you shift a colour, and is the reason that channel exists."""
    import numpy as np
    from nocturne.core.curves import _hue_sat
    # Dim and only half saturated ON PURPOSE. Hue preservation is a property of
    # the RATIO rescale, and the final clip to [0,1] breaks it: a bright
    # saturated pixel boosted past 1.0 in its strongest channel comes back with
    # a different hue. apply_curve has always behaved that way; this test is
    # about the rescale, so it stays inside the range where the clip is inert.
    px = _hue_strip([0.08], value=0.30, sat=0.6)     # an orange-ish pixel
    rgb_out = apply_curves(_img(px), {curve_key("rgb", "all"): _BOOST}).data
    r_out = apply_curves(_img(px), {curve_key("r", "all"): _BOOST}).data
    h0 = float(_hue_sat(px)[0][0, 0])
    assert abs(float(_hue_sat(rgb_out)[0][0, 0]) - h0) < 1e-3, "RGB must hold hue"
    assert abs(float(_hue_sat(r_out)[0][0, 0]) - h0) > 1e-3, "R alone must shift it"


def test_the_saturation_curve_changes_saturation_and_not_luminance():
    import numpy as np
    from nocturne.core.curves import _hue_sat
    px = _hue_strip([0.02, 0.4, 0.7], value=0.6, sat=0.5)
    out = apply_curves(_img(px), {curve_key("s", "all"): _BOOST}).data
    assert float(_hue_sat(out)[1].mean()) > float(_hue_sat(px)[1].mean())
    assert np.allclose(out.mean(axis=2), px.mean(axis=2), atol=1e-3), \
        "chroma is scaled about luminance, so luminance must survive"


def test_curves_are_applied_in_a_fixed_order_whatever_the_dict_order():
    """These do not commute. A dialog that applied them in whatever order the
    user happened to edit would give two different pictures from identical
    settings, and a recipe would not reproduce."""
    import numpy as np
    # sat=0.6, NOT the default 1.0. At full saturation the S curve maps 1.0 to
    # 1.0 and is a no-op, so the two orders agree trivially and this test proves
    # nothing — it passed with the ordering removed until the fixture was fixed.
    px = _hue_strip([0.02, 0.35, 0.62], value=0.7, sat=0.6)
    a = {curve_key("r", "all"): _BOOST, curve_key("s", "all"): _BOOST}
    b = {curve_key("s", "all"): _BOOST, curve_key("r", "all"): _BOOST}
    assert np.array_equal(apply_curves(_img(px), a).data,
                          apply_curves(_img(px), b).data)


def test_identity_slots_cost_nothing_and_report_nothing():
    import numpy as np
    img = _img(np.random.default_rng(1).random((5, 5, 3)).astype(np.float32))
    only_identities = {curve_key(c, "all"): _IDENT for c in CURVE_CHANNELS}
    assert np.array_equal(apply_curves(img, only_identities).data, img.data)
    assert normalize_curves(only_identities) == {}
    assert active_curves(only_identities) == []


def test_active_curves_names_the_slots_in_channel_order():
    """The matrix has 35 slots and hides its own state: without this line the
    user cannot tell that a curve set on Reds twenty minutes ago is still
    shaping the picture."""
    got = active_curves({curve_key("s", "reds"): _BOOST,
                         curve_key("rgb", "all"): _BOOST,
                         curve_key("b", "cyans"): _BOOST})
    assert got == ["RGB", "B·Cyans", "S·Reds"], got


def test_a_mono_frame_takes_the_tone_curve_and_ignores_the_rest():
    """A mono frame can legitimately reach a recipe written on a colour one.
    Ignoring the colour slots beats raising."""
    import numpy as np
    mono = _img(np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8))
    out = apply_curves(mono, {curve_key("rgb", "all"): _BOOST,
                              curve_key("s", "reds"): _BOOST}).data
    assert np.allclose(out, apply_curve(mono, _BOOST).data)
