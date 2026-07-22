"""Overlay geometry: compass (N/E screen directions) and a round scale bar,
derived from a plate-solved WCS. Pure math, no Qt."""
from __future__ import annotations

import numpy as np

from ..tools.astap import FITS_Y_DOWN

_NICE_ARCMIN = [1, 2, 5, 10, 15, 30, 60, 120]


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
    target_arcmin = (width_px * 0.20 * pixscale_arcsec) / 60.0
    nice = min(_NICE_ARCMIN, key=lambda a: abs(a - target_arcmin))
    length_px = int(round(nice * 60.0 / pixscale_arcsec))
    label = f"{nice // 60}°" if nice >= 60 and nice % 60 == 0 else f"{nice}′"
    return length_px, label
