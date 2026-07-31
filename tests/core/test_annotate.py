import numpy as np
from astropy.wcs import WCS

from nocturne.core.annotate import compass_angles, scale_bar


def _wcs(w=1920, h=1080, scale=0.0005556):
    wc = WCS(naxis=2)
    wc.wcs.crpix = [w / 2, h / 2]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-scale, 0], [0, scale]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wc


def test_compass_north_points_up_for_standard_wcs():
    # Standard astro orientation (N up, E left) with FITS_Y_DOWN flip -> on a
    # top-row-first display, North points UP (screen angle ~ -90 / 270).
    n, e = compass_angles(_wcs(), (1080, 1920))
    assert abs(((n % 360) - 270) % 360) < 15 or abs((n % 360) - 270) < 15
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
