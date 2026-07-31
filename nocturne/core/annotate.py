"""Overlay geometry: compass (N/E screen directions) and a round scale bar,
derived from a plate-solved WCS. Pure math, no Qt."""
from __future__ import annotations

import numpy as np

from ..tools.astap import FITS_Y_DOWN

_NICE_ARCSEC = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 18000]


def _screen_xy(wcs, ra, dec, h):
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    x, y = wcs.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
    return float(x), (float(h - 1 - y) if FITS_Y_DOWN else float(y))


def compass_angles(wcs, shape) -> tuple[float, float]:
    """Screen angles (deg, 0=+x, 90=down) of North and East at frame centre."""
    h, w = shape
    ra0, dec0 = wcs.wcs.crval
    x0, y0 = _screen_xy(wcs, ra0, dec0, h)
    d = 0.05  # degrees step
    xn, yn = _screen_xy(wcs, ra0, dec0 + d, h)                  # North
    xe, ye = _screen_xy(wcs, ra0 + d / np.cos(np.radians(dec0)), dec0, h)  # East
    north = float(np.degrees(np.arctan2(yn - y0, xn - x0)))
    east = float(np.degrees(np.arctan2(ye - y0, xe - x0)))
    return north % 360, east % 360


def format_ra_hms(ra_deg: float) -> str:
    """RA in sexagesimal hours, e.g. '20h 59m 17s'. Wraps into [0, 360) first
    so a centre a hair over/under the 0/360 seam (or slightly negative from
    upstream maths) still reads as a sane time rather than '24h' or a bare
    minus sign."""
    ra_deg = ra_deg % 360.0
    total_s = ra_deg / 15.0 * 3600.0        # seconds of time
    h, rem = divmod(total_s, 3600.0)
    m, s = divmod(rem, 60.0)
    h, m, s = int(h), int(m), round(s)
    if s >= 60:                             # rounding carry: 59.6s -> 60 -> 1m
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        h += 1
    h %= 24
    return f"{h:02d}h {m:02d}m {s:02d}s"


def format_dec_dms(dec_deg: float) -> str:
    """Dec in sexagesimal degrees, e.g. '+44° 31′ 44″' or '-0° 30′ 00″'. The
    sign is pulled off BEFORE abs() so a declination between 0 and -1 deg —
    where int(dec_deg) alone truncates to 0 and silently loses the minus —
    still renders negative."""
    sign = "-" if dec_deg < 0 else "+"
    total_s = abs(dec_deg) * 3600.0         # arcsec
    d, rem = divmod(total_s, 3600.0)
    m, s = divmod(rem, 60.0)
    d, m, s = int(d), int(m), round(s)
    if s >= 60:                             # rounding carry
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return f"{sign}{d:02d}° {m:02d}′ {s:02d}″"


def format_orientation(north_angle_deg: float) -> str:
    """North's on-screen rotation as e.g. 'N +12.4°': degrees clockwise the
    frame is turned away from camera-up. compass_angles() returns 270 for
    'North straight up, no rotation' (screen convention 0=+x, 90=down), so we
    re-centre on that and wrap to (-180, 180] for the nearest reading."""
    rot = ((north_angle_deg - 270.0 + 180.0) % 360.0) - 180.0
    return f"N {rot:+.1f}°"


def is_mirrored(wcs, shape) -> bool:
    """True if the frame is flipped left-right relative to the standard,
    undistorted sky view (North up, East left) -- derived from the RELATIVE
    sense of compass_angles' two outputs, which already bakes in the
    FITS_Y_DOWN screen convention, so no separate flip logic is needed here.

    Standard sky: East sits ~90 deg counter-clockwise of North on screen, so
    the wrapped difference lands near 180. Mirrored: it lands near 0/360.
    Rotation-invariant -- only the frame's chirality matters, not its position
    angle -- verified against a synthetic WCS rotated 45 deg in
    tests/core/test_annotate.py.

    The sense here follows FITS_Y_DOWN: that constant was corrected to False on
    2026-07-31 after a real solve showed every annotation was being mirrored
    vertically, which also inverted what this function reported."""
    north, east = compass_angles(wcs, shape)
    return ((east - north) % 360.0) >= 180.0


def scale_bar(pixscale_arcsec: float, width_px: int) -> tuple[int, str]:
    """A bar covering roughly a fifth of the frame, rounded to a readable
    angular length. Chosen from the actual frame width so it works on both a
    tiny high-resolution crop and a many-degree field, and returns nothing at
    all rather than dividing by zero on an unsolved/invalid scale."""
    if pixscale_arcsec <= 0 or width_px <= 0:
        return 0, ""
    target = width_px * 0.20 * pixscale_arcsec              # arcsec
    nice = min(_NICE_ARCSEC, key=lambda a: abs(a - target))
    length_px = int(round(nice / pixscale_arcsec))
    if nice >= 3600:
        label = f"{nice // 3600}°"
    elif nice >= 60:
        label = f"{nice // 60}′"
    else:
        label = f"{nice}″"
    return length_px, label
