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
