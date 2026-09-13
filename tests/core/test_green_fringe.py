import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import remove_green_fringe, _suppress_green_excess


def _screen(a, b):
    return 1.0 - (1.0 - a) * (1.0 - b)


def test_suppress_green_excess_reduces_green_keeps_rb():
    data = np.zeros((1, 1, 3), np.float32)
    data[0, 0] = (0.2, 0.8, 0.3)                 # avg_rb 0.25, excess 0.55
    out = _suppress_green_excess(data, 0.5)
    assert np.isclose(out[0, 0, 1], 0.8 - 0.5 * 0.55)
    assert np.isclose(out[0, 0, 0], 0.2) and np.isclose(out[0, 0, 2], 0.3)


def test_suppress_green_excess_noop_on_neutral_and_zero():
    grey = np.full((2, 2, 3), 0.5, np.float32)
    assert np.allclose(_suppress_green_excess(grey, 1.0), grey)          # excess 0
    g = np.zeros((1, 1, 3), np.float32); g[0, 0] = (0.2, 0.8, 0.3)
    assert np.allclose(_suppress_green_excess(g, 0.0), g)                # strength 0


def _layers():
    starless = AstroImage(np.full((4, 4, 3), 0.3, np.float32), is_linear=False,
                          metadata={"k": 1})
    stars = np.zeros((4, 4, 3), np.float32)
    stars[2, 2] = (0.2, 0.9, 0.3)                # a green-fringed star pixel
    return starless, AstroImage(stars, is_linear=False)


def test_strength_zero_is_plain_recombine():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 0.0).data
    assert np.allclose(out, _screen(starless.data, stars.data))


def test_degreens_star_pixel_only_background_untouched():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 1.0).data
    # star pixel green reduced vs the plain recombine
    plain = _screen(starless.data, stars.data)
    assert out[2, 2, 1] < plain[2, 2, 1]
    # a background pixel (stars==0 there) equals the untouched starless value
    assert np.allclose(out[0, 0], starless.data[0, 0])


def test_range_dtype_and_metadata_from_starless():
    starless, stars = _layers()
    out = remove_green_fringe(starless, stars, 0.7)
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.is_linear is False and out.metadata == {"k": 1}


def test_repeat_application_settles_greens_but_keeps_eroding_the_band_edges():
    """Pins what repeating the step actually does — which is NOT idempotent,
    unlike the SCNR clamp this replaced.

    Desaturating toward grey preserves HUE, so a pixel at full weight lands on
    neutral and has no hue left to match on the next pass (stable), while one
    in the ramp keeps its green hue at lower saturation and gets pulled a
    further fraction of the way each time. Measured: a hue-150 pixel goes
    0.933 -> 0.528 -> 0.283 -> 0.146 saturation over four applications.

    That is reachable — Auto Enhance's De-green Stars plus a manual one are two
    separate history entries, and a recipe can replay onto an image that
    already has it. It is mild and nobody has asked for a fix; this test exists
    so that if it ever stops being mild, something says so.
    """
    from nocturne.core.color import _desaturate_greens

    full = np.array([[[0.21, 0.83, 0.21]]], np.float32)     # hue 120, weight 1.0
    once = _desaturate_greens(full, 1.0)
    assert np.allclose(_desaturate_greens(once, 1.0), once, atol=1e-6), \
        "a pixel already on neutral must never move again"

    edge = np.array([[[0.05, 0.75, 0.40]]], np.float32)     # hue 150, weight 0.5
    def sat(a):
        mx, mn = float(a.max()), float(a.min())
        return (mx - mn) / max(mx, 1e-9)
    s0 = sat(edge)
    s1 = sat(_desaturate_greens(edge, 1.0))
    s2 = sat(_desaturate_greens(_desaturate_greens(edge, 1.0), 1.0))
    assert s1 < s0 and s2 < s1, "a band-edge pixel keeps desaturating"
    assert s2 > 0.15 * s0, \
        "two applications should erode the band edge, not collapse it"


def test_degreening_leaves_a_fourth_channel_alone():
    """Guards the `[..., :3]` slicing. An RGBA array reaches this through
    export paths, and a de-green that wrote over alpha would silently make
    parts of a saved image transparent."""
    from nocturne.core.color import _desaturate_greens
    data = np.zeros((3, 3, 4), np.float32)
    data[...] = (0.21, 0.83, 0.24, 0.55)
    out = _desaturate_greens(data, 1.0)
    assert np.allclose(out[..., 3], 0.55), "alpha must be untouched"
    assert abs(float(out[0, 0, 0] - out[0, 0, 1])) < 1e-6, "...and RGB still de-greened"
