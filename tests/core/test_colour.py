"""Converting the finished image into the space it will be declared to be in.

Astro data has no source colour space — a FITS is photon counts — so the image's
colour is created by the pipeline and judged by the user on a calibrated,
sRGB-fed display. sRGB is therefore what the numbers already mean, and these
conversions start from it.
"""
import numpy as np
import pytest

from nocturne.core import colour as C


def _ramp():
    """A spread of colours, including neutrals and saturated primaries."""
    return np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.5, 0.5, 0.5]],
                     [[0.9, 0.2, 0.2], [0.2, 0.9, 0.2], [0.2, 0.2, 0.9]],
                     [[0.15, 0.16, 0.17], [0.7, 0.6, 0.5], [0.3, 0.45, 0.8]]],
                    dtype=np.float32)


def test_srgb_to_srgb_changes_nothing_at_all():
    """The default path must be a true no-op.

    Assert-UNCHANGED, not 'close': every existing export goes through here, and
    a conversion that is nearly the identity would shift everyone's output by a
    little for no reason.
    """
    a = _ramp()
    out = C.convert(a.copy(), "sRGB")
    assert np.array_equal(out, a)


def test_converting_actually_changes_the_pixels():
    """A relabel is not a conversion. If this passes with the matrix removed,
    the feature is a lie told with metadata."""
    a = _ramp()
    out = C.convert(a, "Adobe RGB")
    assert not np.allclose(out, a, atol=1e-4), "the pixels did not move"


def test_a_round_trip_returns_the_original():
    """sRGB -> Adobe RGB -> sRGB. Tolerance stated in 8-bit levels so a wrong
    matrix or a missing transfer function shows up rather than being absorbed."""
    a = _ramp()
    there = C.convert(a, "Adobe RGB")
    back = C.convert(there, "sRGB", frm="Adobe RGB")
    worst = float(np.abs(back - a).max()) * 255
    assert worst < 0.5, f"round trip lost {worst:.2f} 8-bit levels"


@pytest.mark.parametrize("space", ["Display P3", "Adobe RGB"])
def test_neutral_grey_stays_neutral(space):
    """The sharpest correctness check available.

    All three spaces share a D65 whitepoint, so a neutral must survive
    conversion as a neutral. A transposed or mis-ordered matrix — the classic
    way to get this wrong — tints the greys immediately, while a colour ramp
    can look plausible.
    """
    greys = np.array([[[v, v, v] for v in (0.05, 0.2, 0.5, 0.8, 0.97)]], np.float32)
    out = C.convert(greys, space)
    spread = np.abs(out - out.mean(axis=2, keepdims=True)).max() * 255
    assert spread < 0.5, f"{space} tinted the greys by {spread:.2f} 8-bit levels"


@pytest.mark.parametrize("space", ["sRGB", "Display P3", "Adobe RGB"])
def test_output_stays_in_range(space):
    """Out-of-gamut results must be clipped, not wrapped: a uint16 cast of a
    negative float is undefined and produced garbage pixels once before."""
    a = _ramp()
    out = C.convert(a, space)
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert out.dtype == np.float32


def test_an_unknown_space_is_refused_loudly():
    with pytest.raises(ValueError, match="unknown colour space"):
        C.convert(_ramp(), "Rec. 2020")


def test_the_offered_spaces_are_the_ones_that_convert():
    """SPACES is what the UI offers. Anything in it must actually work, or the
    dropdown promises something that raises."""
    for name in C.SPACES:
        C.convert(_ramp(), name)


def test_it_matches_a_published_reference_value():
    """THE correctness test, against a figure this code cannot fabricate.

    sRGB pure red converted to Adobe RGB (1998) is about (219, 0, 0) in 8-bit —
    a widely published value. Applying the matrix to gamma-ENCODED values, which
    is the classic way to get colour conversion wrong, gives (182, 0, 0)
    instead.

    A round trip cannot catch that: an invertible-but-wrong transform round
    trips perfectly, and this one did — the round-trip test passed with the
    transfer functions disabled. Only an absolute reference discriminates.
    """
    red = np.array([[[1.0, 0.0, 0.0]]], np.float32)
    out = C.convert(red, "Adobe RGB")[0, 0] * 255
    assert abs(out[0] - 219) < 2, f"sRGB red -> Adobe RGB gave {out}, expected ~219"
    assert out[1] < 2 and out[2] < 2, f"red gained other channels: {out}"


def test_out_of_gamut_colours_do_not_become_nan():
    """A saturated colour goes negative in linear light after the matrix, and a
    negative raised to a fractional exponent is NaN. np.clip does not remove
    NaN, so it would be cast into the file — and casting NaN to an unsigned
    integer is undefined, which produced garbage pixels here once before.

    The gamut clip therefore happens in LINEAR light, before the encode.
    """
    import warnings
    saturated = np.array([[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
                           [1.0, 0.0, 1.0], [0.0, 1.0, 1.0]]], np.float32)
    for space in C.SPACES:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = C.convert(saturated, space)
        assert np.isfinite(out).all(), f"{space} produced NaN or inf"
        assert out.min() >= 0.0 and out.max() <= 1.0
        # The clip must happen BEFORE the encode. Clipping afterwards reaches
        # the same numbers — nan_to_num zeroes the NaN and encode(0) is also 0 —
        # so the outputs alone cannot tell the two apart. What does tell them
        # apart is that the wrong order raises a RuntimeWarning on every
        # out-of-gamut pixel, which is the signal that NaN was created at all.
        bad = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        assert not bad, f"{space} created NaN before clipping: {[str(w.message) for w in bad]}"


@pytest.mark.parametrize("space", ["Adobe RGB", "Display P3", "ProPhoto RGB"])
def test_it_agrees_with_littlecms(space):
    """Cross-check against a SECOND, independent implementation.

    Ours goes through colour-science's matrices; this goes through littlecms
    using the actual ICC profiles. Two different code paths arriving at the same
    numbers is far stronger evidence than a reference figure quoted from memory
    — and it needed to be, because the figure originally quoted here for
    ProPhoto (179, 70, 42) was simply wrong, while both implementations agree on
    (179, 70, 26).

    The conversion uses BRADFORD adaptation, as the ICC specification requires
    and as littlecms and Photoshop therefore do. colour-science defaults to
    CAT02, which was out by 4.5 levels on ProPhoto — a real divergence from
    Photoshop in a feature whose whole purpose is matching it.

    TWO tolerances, because one number would hide the shape of the difference:

    * worst case 3 levels, which only a maximally saturated PRIMARY reaches.
      Pure sRGB blue sits on Adobe RGB's gamut boundary, so its linear red lands
      within rounding distance of zero, and that space's gamma lifts near-zero
      values steeply — ours gives 3, littlecms 0. A clipping artefact at the
      very corner of the gamut, not a systematic shift.
    * MEDIAN half a level, which is what actually catches a wrong matrix, a
      missing transfer function or the wrong adaptation. Those move every
      colour; a boundary artefact moves one.
    """
    import io
    from PIL import Image, ImageCms
    from PySide6.QtGui import QColorSpace
    from nocturne.colour_profiles import _QT_NAME

    def profile(name):
        cs = QColorSpace(getattr(QColorSpace.NamedColorSpace, _QT_NAME[name]))
        return ImageCms.ImageCmsProfile(io.BytesIO(bytes(cs.iccProfile())))

    src = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0],
                     [128, 128, 128], [40, 90, 160], [200, 120, 60]]], np.uint8)
    lcms = np.array(ImageCms.profileToProfile(
        Image.fromarray(src, "RGB"), profile("sRGB"), profile(space),
        outputMode="RGB", renderingIntent=1)).astype(float)
    ours = C.convert(src.astype(np.float32) / 255.0, space) * 255
    diff = np.abs(ours - lcms)
    worst, typical = float(diff.max()), float(np.median(diff))
    assert worst <= 3.0, f"{space}: worst {worst:.1f} levels from littlecms"
    assert typical <= 0.5, (
        f"{space}: median {typical:.2f} levels from littlecms — a systematic "
        "difference, not a gamut-boundary artefact")
