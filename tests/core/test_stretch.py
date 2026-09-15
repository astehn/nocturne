import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.stretch import apply_stretch, amount_to_target


def _faint():
    rng = np.random.default_rng(0)
    data = np.clip(rng.normal(0.003, 0.0008, (64, 64, 3)), 0, 1).astype(np.float32)
    data[20:40, 20:40] += 0.02  # faint nebula
    data[0, 0] = 1.0            # a bright star driving the max
    return AstroImage(data)


def test_stretch_marks_nonlinear():
    out = apply_stretch(_faint(), 0.5)
    assert out.is_linear is False
    assert out.data.dtype == np.float32


def test_stretch_lifts_faint_background():
    out = apply_stretch(_faint(), 0.5)
    # adaptive stretch must lift the background well above the raw ~0.003
    assert np.median(out.data) > 0.15


def test_larger_amount_brightens_more():
    img = _faint()
    low = np.median(apply_stretch(img, 0.1).data)
    high = np.median(apply_stretch(img, 0.9).data)
    assert high > low


def test_amount_clamped():
    assert amount_to_target(-1) == amount_to_target(0.0)
    assert amount_to_target(5) == amount_to_target(1.0)


def test_output_in_range():
    out = apply_stretch(_faint(), 1.0)
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


# --- linked vs unlinked ---------------------------------------------------
# The stretch gains a mechanism choice, not a second degree of aggressiveness.
# Neither is the correct one: the measurement that would settle that is still
# unresolved (see the spec). What is settled is that the user picks by eye.

def _two_tone_linear():
    """Channels deliberately NOT interchangeable.

    A fixture whose channels commute cannot tell a linked stretch from an
    unlinked one — both would return the same array and every assertion below
    would pass against a broken dispatch. Red is given a wider spread, which is
    the real asymmetry on Andreas's data (R/G MAD ratio 2.67 on IC 1396A).
    """
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.02, 0.005, (64, 48, 3)), 0, 1).astype(np.float32)
    d[..., 0] = np.clip(0.02 + (d[..., 0] - 0.02) * 2.67, 0, 1)
    return AstroImage(d, is_linear=True)


def test_linked_is_exactly_neutral_stretch():
    """Asserted against the function itself, so the dispatch cannot drift."""
    from nocturne.core.autostretch import neutral_stretch
    img = _two_tone_linear()
    assert np.array_equal(apply_stretch(img, 0.30, linked=True).data,
                          neutral_stretch(img.data, amount_to_target(0.30)))


def test_unlinked_is_exactly_unlinked_stretch():
    from nocturne.core.autostretch import unlinked_stretch
    img = _two_tone_linear()
    assert np.array_equal(apply_stretch(img, 0.30, linked=False).data,
                          unlinked_stretch(img.data, amount_to_target(0.30)))


def test_the_two_mechanisms_actually_differ():
    img = _two_tone_linear()
    assert not np.allclose(apply_stretch(img, 0.30, linked=True).data,
                           apply_stretch(img, 0.30, linked=False).data)


def test_default_is_linked():
    """Every option written before 2026-09-14 means linked; so does every call
    site that has not been touched."""
    img = _two_tone_linear()
    assert np.array_equal(apply_stretch(img, 0.30).data,
                          apply_stretch(img, 0.30, linked=True).data)


def test_the_choice_does_not_leak_into_the_metadata():
    """It is a mechanism, not a property of the capture."""
    img = _two_tone_linear()
    out = apply_stretch(img, 0.30, linked=False)
    assert "linked" not in out.metadata
    assert out.is_linear is False


# --- the preview and the commit agree ------------------------------------
# They disagreed from 2026-09-14, when the default came down 0.43 -> 0.30 and
# the LINEAR preview's target did not follow. Walking into Stretch darkened the
# canvas 18% — about 10 levels of 255 — before the user touched anything.
# Andreas saw it independently: "yes i actually noticed that as well earlier
# today". Two hand-maintained numbers for one fact is how they drifted, so there
# is one fact now and both derive from it.

# One 8-bit level. The amount<->target round trip is float arithmetic, so exact
# equality is not achievable (0.205 -> 0.3 -> 0.20500000000000002) and demanding
# it would be false precision. What has to hold is that the picture does not
# VISIBLY change, and a level is the smallest thing that could be seen.
_ONE_LEVEL = 1 / 255


def test_the_linear_preview_targets_what_the_default_commit_produces():
    from nocturne.core.autostretch import _TARGET_BG
    from nocturne.steps.stretch_step import _DEFAULT
    assert abs(_TARGET_BG - amount_to_target(_DEFAULT)) < _ONE_LEVEL


def test_arriving_at_stretch_does_not_change_the_picture():
    """The invariant as a user meets it, measured rather than asserted on
    constants: what you were looking at before Stretch is what the untouched
    slider gives you."""
    from nocturne.core.autostretch import autostretch
    from nocturne.steps.stretch_step import _DEFAULT

    img = _two_tone_linear()
    before = autostretch(img)
    after = apply_stretch(img, _DEFAULT).data
    sky = lambda a: float(np.percentile(a.mean(axis=2), 35))
    assert abs(sky(before) - sky(after)) < 0.005, (sky(before), sky(after))


def test_the_slider_default_is_derived_not_copied():
    """Change the one fact and BOTH move. The previous arrangement had 0.25 in
    autostretch and 0.30 in stretch_step, each maintained by hand."""
    from nocturne.core import autostretch
    from nocturne.steps.stretch_step import _DEFAULT
    assert abs(amount_to_target(_DEFAULT) - autostretch.DEFAULT_TARGET_BG) < _ONE_LEVEL
    assert autostretch._TARGET_BG is autostretch.DEFAULT_TARGET_BG


def test_the_panel_default_matches_the_step_default():
    """STRETCH_DEFAULT is the slider's integer position; a third copy of the
    same fact would drift the same way."""
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    from nocturne.steps.stretch_step import _DEFAULT
    assert STRETCH_DEFAULT == round(_DEFAULT * 100)
