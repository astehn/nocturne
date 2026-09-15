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
