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
    in the ramp keeps its hue at lower saturation and gets pulled a further
    fraction of the way each time.

    The ramp pixel was hue 150 until 2026-09-19, when the band widened to reach
    cyan and hue 150 became plateau — full weight, neutral in one pass, nothing
    left to erode. The property under test did not change; only where the ramp
    is. It now sits at hue 202, between the 190 plateau edge and the 214 cutoff
    that keeps blue stars.

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

    edge = np.array([[[0.10, 0.48, 0.70]]], np.float32)     # hue 202, weight 0.5
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


def test_teal_stars_are_drained_and_blue_stars_are_not():
    """The defect this tool exists for, and the star colour it must never touch.

    Andreas, after three passes at De-green Stars: *"the tool still does nothing
    for my images."* It was working correctly and finding almost nothing,
    because his stars are not green — they are TEAL, and the band ran 75-165 deg
    with a `g >= b` guard, so cyan at 180 deg scored exactly zero by
    construction.

    Both halves are pinned here because they are in tension: every widening that
    reaches teal moves toward blue, and blue stars are real. Stars are never
    green and never cyan — the blackbody locus runs red-orange-yellow-white-blue
    and passes through neither — which is exactly why one is safe to drain and
    the other is not.
    """
    from nocturne.core.color import _green_weight

    def w(rgb):
        return float(_green_weight(np.array([[rgb]], np.float32))[0, 0])

    # the defect
    assert w((0.05, 0.69, 0.75)) == 1.0, "a teal star must be fully drained"
    assert w((0.11, 0.80, 0.80)) == 1.0, "and so must pure cyan"
    # the colours that must survive, each for a different reason
    assert w((0.18, 0.31, 0.88)) == 0.0, "a blue star is real — the band stops short"
    assert w((0.10, 0.30, 0.70)) == 0.0, "and so is the blue side of the cutoff"
    assert w((0.92, 0.46, 0.12)) == 0.0, "orange is protected by g >= r, not by the band"
    assert w((0.90, 0.85, 0.35)) == 0.0, "so is yellow"
    assert w((0.9, 0.9, 0.9)) == 0.0, "and a neutral star has no hue to match"


def test_the_band_cannot_be_widened_into_blue_stars_by_accident():
    """A guard on the constant itself. The band reaching blue is the one way
    this tool can damage real star colour, and it is a plausible edit: every
    round of "it still does not catch my stars" pushes the cutoff outward."""
    from nocturne.core.color import _GREEN_BAND

    assert _GREEN_BAND[3] <= 220.0, \
        "past ~220 deg the band starts draining genuinely blue stars"
    assert _GREEN_BAND[0] < _GREEN_BAND[1] < _GREEN_BAND[2] < _GREEN_BAND[3]


def test_the_star_floor_spares_faint_noise_and_keeps_bright_stars():
    """The stars layer is not only stars — it carries the noise speckle the
    split did not put in the starless frame. Measured on a real master, without
    a floor only 15.5% of the pixels this step changed were on or beside a star.

    The floor is honest about being partial: faint stars and noise overlap in
    brightness, so it buys about a quarter less background change for under 1%
    of the star correction. The real fix is ordering — De-green Stars runs
    before Noise Reduction — and is filed separately.
    """
    from nocturne.core.color import _desaturate_greens, _STAR_FLOOR, _LUM_WEIGHTS

    teal = np.array([0.05, 0.69, 0.75], np.float32)
    bright = teal * 1.0                                   # a real star: well above the floor
    faint = teal * 0.02                                   # speckle: well below it
    assert float(bright @ _LUM_WEIGHTS) > _STAR_FLOOR
    assert float(faint @ _LUM_WEIGHTS) < _STAR_FLOOR

    data = np.stack([bright, faint])[None, :, :]
    out = _desaturate_greens(data, 1.0, floor=_STAR_FLOOR)
    assert not np.allclose(out[0, 0], bright), "a bright teal star must still be drained"
    assert np.allclose(out[0, 1], faint), "faint speckle must be left alone"

    # and with no floor the faint pixel IS treated — otherwise this pins nothing
    assert not np.allclose(_desaturate_greens(data, 1.0)[0, 1], faint)


def test_pixels_with_no_star_signal_are_left_exactly_alone():
    """The invariant behind the floor, and the answer to a scare of my own making.

    Andreas reported the background going red, and a first measurement agreed:
    +0.90 of an 8-bit level on his NGC 281 master. That measurement called
    everything outside the brightest 0.5% of the stars layer "background" —
    which on a dense field is 94.5% of the frame and still contains most of the
    stars. Defining background as "the stars layer has no signal here" instead,
    the shift is +0.00 on NGC 281, NGC 7635 and M 45 alike.

    So the step does not tint the sky; what reads as background changing is
    thousands of faint stars losing their teal. A neutrality correction was
    written for the imagined defect and reverted — this test is what stays, so
    the claim is checked rather than remembered.
    """
    from nocturne.core.color import remove_green_fringe
    from nocturne.core.image import AstroImage

    rng = np.random.default_rng(11)
    h = w = 48
    # a cool-leaning sky, the condition that produced the scare
    sky = np.stack([rng.normal(0.18, 0.01, (h, w)),
                    rng.normal(0.20, 0.01, (h, w)),
                    rng.normal(0.21, 0.01, (h, w))], -1).astype(np.float32)
    starless = AstroImage(np.clip(sky, 0, 1), is_linear=False)

    st = np.zeros((h, w, 3), np.float32)
    st[24, 24] = (0.05, 0.69, 0.75)          # one bright teal star, and nothing else
    stars = AstroImage(st, is_linear=False)

    plain = remove_green_fringe(starless, stars, 0.0).data
    out = remove_green_fringe(starless, stars, 1.0).data

    empty = np.ones((h, w), bool)
    empty[23:26, 23:26] = False              # everywhere the stars layer is zero
    assert np.allclose(out[empty], plain[empty], atol=1e-6), \
        "a pixel with no star signal must come through the step untouched"
    assert not np.allclose(out[24, 24], plain[24, 24]), \
        "and the one star must still be drained, or this proves nothing"
