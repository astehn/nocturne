"""Photometric (SPCC-lite) white balance: fit the sensor's measured star colours
against Gaia BP-RP, then set per-channel gains so a solar-type star renders
neutral. Pure — takes a solved WCS and a Gaia star list, no network, no Qt."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import sep

from ..tools.astap import FITS_Y_DOWN
from .image import AstroImage

_BP_RP_SUN = 0.82        # solar colour -> the neutral reference
_THRESH = 5.0            # sep detection sigma
_MATCH_PX = 5.0          # cross-match tolerance (undersampled Seestar stars + WCS residual)
_SAT = 0.95             # skip stars with a channel this close to clipping
_MIN_STARS = 15
_GAIN_LO, _GAIN_HI = 0.2, 5.0


@dataclass
class SpccResult:
    gains: tuple[float, float, float]
    n_matched: int


def _measure(data):
    """Detect stars on luminance; return (x, y, peakmax, flux[N,3]) or None."""
    lum = np.ascontiguousarray(data.mean(axis=2), dtype=np.float32)
    try:
        bkg = sep.Background(lum)
        obj = sep.extract(lum - bkg.back(), _THRESH, err=bkg.globalrms)
    except Exception:
        return None
    if len(obj) == 0:
        return None
    x, y = obj["x"].astype(float), obj["y"].astype(float)
    r = np.clip(2.5 * np.sqrt(obj["a"] * obj["b"]), 2.0, 12.0)
    flux = np.zeros((len(obj), 3), np.float32)
    for c in range(3):
        chan = np.ascontiguousarray(data[..., c], dtype=np.float32)
        f, _, _ = sep.sum_circle(chan, x, y, r, err=bkg.globalrms)
        flux[:, c] = f
    xi = np.clip(np.round(y).astype(int), 0, data.shape[0] - 1)
    yi = np.clip(np.round(x).astype(int), 0, data.shape[1] - 1)
    peakmax = data[xi, yi].max(axis=1)
    return x, y, peakmax, flux


def _robust_fit(x, y, iters=3, sigma=2.5):
    keep = np.ones(len(x), bool)
    a = b = None
    for _ in range(iters):
        if keep.sum() < 5:
            break
        b, a = np.polyfit(x[keep], y[keep], 1)       # slope, intercept
        resid = y - (a + b * x)
        s = float(np.std(resid[keep]))
        if s == 0:
            break
        keep = np.abs(resid) <= sigma * s
    return (a, b) if a is not None else (None, None)


def photometric_gains(img: AstroImage, wcs, gaia, *, min_stars=_MIN_STARS, report=None):
    """`report`, if given, is filled with diagnostic counts (n_catalogue, n_detected,
    n_matched) whether or not the fit succeeds — for surfacing why it fell back."""
    if report is not None:
        report.update(n_catalogue=len(gaia), n_detected=0, n_matched=0)
    if not img.is_color or not gaia:
        return None
    data = np.clip(img.data.astype(np.float32), 0.0, None)
    m = _measure(data)
    if m is None:
        return None
    x, y, peakmax, flux = m
    h, w = data.shape[:2]
    if report is not None:
        report["n_detected"] = len(x)

    from astropy.coordinates import SkyCoord
    import astropy.units as u
    gra = np.array([s.ra_deg for s in gaia]); gdec = np.array([s.dec_deg for s in gaia])
    gbprp = np.array([s.bp_rp for s in gaia])
    gx, gy = wcs.world_to_pixel(SkyCoord(gra * u.deg, gdec * u.deg))
    gx = np.asarray(gx, float); gy = np.asarray(gy, float)
    if FITS_Y_DOWN:
        gy = (h - 1) - gy

    cols, R, G, B = [], [], [], []
    nearest = []                                         # nearest detected-star distance, per in-frame Gaia star
    for i in range(len(gx)):
        if not (np.isfinite(gx[i]) and np.isfinite(gy[i])):
            continue
        if not (0 <= gx[i] < w and 0 <= gy[i] < h):     # only Gaia stars projecting into the frame
            continue
        d2 = (x - gx[i]) ** 2 + (y - gy[i]) ** 2
        j = int(np.argmin(d2))
        nearest.append(float(d2[j]) ** 0.5)
        if d2[j] > _MATCH_PX ** 2 or peakmax[j] >= _SAT:
            continue
        r, g, b = flux[j]
        if r <= 0 or g <= 0 or b <= 0:
            continue
        cols.append(gbprp[i]); R.append(r); G.append(g); B.append(b)
    if report is not None:
        report["n_in_frame"] = len(nearest)
        report["median_offset_px"] = float(np.median(nearest)) if nearest else -1.0
    if report is not None:
        report["n_matched"] = len(cols)
    if len(cols) < min_stars:
        return None

    cols = np.array(cols); R = np.array(R); G = np.array(G); B = np.array(B)
    aR, bR = _robust_fit(cols, np.log10(R / G))
    aB, bB = _robust_fit(cols, np.log10(B / G))
    if aR is None or aB is None:
        return None
    gains = np.array([10.0 ** -(aR + bR * _BP_RP_SUN), 1.0,
                      10.0 ** -(aB + bB * _BP_RP_SUN)], float)
    gains = gains / np.exp(np.mean(np.log(gains)))       # geom-mean 1 -> preserve brightness
    if not np.all((gains >= _GAIN_LO) & (gains <= _GAIN_HI)):
        return None
    return SpccResult((float(gains[0]), float(gains[1]), float(gains[2])), len(cols))


def apply_gains(img: AstroImage, gains) -> AstroImage:
    out = img.data.astype(np.float32) * np.array(gains, np.float32)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))
