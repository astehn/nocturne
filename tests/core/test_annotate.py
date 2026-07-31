import numpy as np
from astropy.wcs import WCS

from nocturne.core.annotate import (
    compass_angles, format_dec_dms, format_orientation, format_ra_hms,
    is_mirrored, scale_bar,
)


def _wcs(w=1920, h=1080, scale=0.0005556, mirrored=False, rotate_deg=0.0):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]; wc.wcs.crval = [100.0, 0.0]
    # Standard (non-mirrored) sky orientation; flipping the RA-axis sign
    # mirrors it (East ends up on the wrong side). Rotating both by the same
    # angle preserves chirality, so it must not change is_mirrored()'s answer.
    x_sign = 1.0 if mirrored else -1.0
    cd = np.array([[x_sign * scale, 0.0], [0.0, scale]])
    if rotate_deg:
        t = np.radians(rotate_deg)
        r = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        cd = r @ cd
    wc.wcs.cd = cd.tolist(); wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


def test_compass_north_points_up_for_standard_wcs():
    # A standard-orientation WCS (Dec increasing with pixel row) drawn on a
    # top-row-first display puts North DOWN the screen (~90 deg), because row 0
    # is the top. FITS_Y_DOWN was False-corrected on 2026-07-31 after a real
    # solve showed the old True flipped every annotation; the compass follows the
    # same _screen_xy as the positions, so it moved with them.
    n, e = compass_angles(_wcs(), (1080, 1920))
    assert abs((n % 360) - 90) < 15, n
    # East is ~90 deg from North
    assert abs(((e - n) % 360) - 90) < 20 or abs(((n - e) % 360) - 90) < 20


def test_scale_bar_picks_round_length():
    length_px, label = scale_bar(2.0, 1920)   # 2 arcsec/px -> 1920 px = 64 arcmin
    # ~20% of 1920 = 384 px = ~12.8 arcmin -> nearest nice = 15 arcmin -> 450 px
    assert label in ("15′", "10′")
    assert 250 < length_px < 500


def test_scale_bar_targets_about_a_fifth_of_the_frame():
    length_px, _ = scale_bar(2.0, 1000)
    assert 120 <= length_px <= 320, length_px


def test_scale_bar_handles_a_very_wide_field_in_degrees():
    _, label = scale_bar(60.0, 1000)          # 60"/px -> a many-degree frame
    assert "°" in label


def test_scale_bar_handles_a_tiny_high_resolution_crop():
    length_px, label = scale_bar(0.2, 400)
    assert length_px > 0 and label


def test_scale_bar_survives_an_invalid_pixel_scale():
    length_px, label = scale_bar(0.0, 1000)
    assert length_px == 0 and label == ""


# --- format_ra_hms / format_dec_dms -----------------------------------------

def test_format_ra_hms_typical_value():
    assert format_ra_hms(314.8208333333334) == "20h 59m 17s"


def test_format_dec_dms_positive_value():
    assert format_dec_dms(44.528888888888886) == "+44° 31′ 44″"


def test_format_dec_dms_negative_value():
    assert format_dec_dms(-44.528888888888886) == "-44° 31′ 44″"


def test_format_dec_dms_between_zero_and_minus_one_keeps_the_sign():
    # int(-0.5) truncates to 0 -- the classic trap where the minus sign is
    # silently lost. Degrees field must still read "-00", not "00".
    assert format_dec_dms(-0.5) == "-00° 30′ 00″"


def test_format_ra_hms_wraps_at_360():
    assert format_ra_hms(-0.5) == "23h 58m 00s"   # just under 0h from the other side
    assert format_ra_hms(360.0) == "00h 00m 00s"  # exactly the wrap seam


def test_format_ra_hms_handles_the_60_second_carry():
    # 5h 10m 59.6s rounds to 5h 11m 00s, not 5h 10m 60s.
    assert format_ra_hms(77.74833333333333) == "05h 11m 00s"


def test_format_dec_dms_handles_the_60_second_carry():
    # 10 deg 20' 59.6" rounds to 10 deg 21' 00", not 10 deg 20' 60".
    assert format_dec_dms(10.34988888888889) == "+10° 21′ 00″"


# --- format_orientation -------------------------------------------------

def test_format_orientation_reports_zero_for_north_up():
    assert format_orientation(270.0) == "N +0.0°"


def test_format_orientation_reports_signed_rotation():
    assert format_orientation(225.0) == "N -45.0°"
    assert format_orientation(315.0) == "N +45.0°"


# --- is_mirrored ---------------------------------------------------------
# Pinned against a synthetic WCS of KNOWN handedness in both directions, per
# the task-7 brief's rule: only derive parity if it can be proven this way.

def test_is_mirrored_false_for_standard_orientation():
    assert is_mirrored(_wcs(mirrored=False), (1080, 1920)) is False


def test_is_mirrored_true_for_flipped_orientation():
    assert is_mirrored(_wcs(mirrored=True), (1080, 1920)) is True


def test_is_mirrored_is_unaffected_by_rotation():
    # Chirality (mirrored or not) must not depend on the solved position
    # angle -- rotating either WCS by the same amount must not flip the
    # verdict, otherwise a normally-rotated real solve could misreport.
    assert is_mirrored(_wcs(mirrored=False, rotate_deg=45.0), (1080, 1920)) is False
    assert is_mirrored(_wcs(mirrored=True, rotate_deg=45.0), (1080, 1920)) is True
