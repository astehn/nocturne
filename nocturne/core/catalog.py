"""Bundled OpenNGC deep-sky catalogue: load rows and project them through a
plate-solved WCS to place annotation labels."""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..tools.astap import FITS_Y_DOWN

_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "openngc.csv")
_STARS = os.path.join(os.path.dirname(__file__), "..", "data", "named_stars.csv")
_LABEL_MARGIN = 8               # keep a clamped label this many px inside the frame
_NAME_RE = re.compile(r"^([A-Za-z]+)0*(\d+)(.*)$")


@dataclass
class CatalogObject:
    name: str
    common: str
    ra_deg: float
    dec_deg: float
    major_arcmin: float
    x: float
    y: float
    centered: bool = True       # True if the object's CENTRE lands inside the frame


@dataclass
class NamedStar:
    name: str                   # IAU proper name, e.g. "Deneb"
    ra_deg: float
    dec_deg: float
    mag: float
    x: float
    y: float


def _pretty_name(name: str) -> str:
    """'NGC0224' -> 'NGC 224', 'IC5070' -> 'IC 5070'. Unmatched names pass through."""
    m = _NAME_RE.match(name)
    if not m:
        return name
    prefix, num, suffix = m.groups()
    return f"{prefix} {num}{suffix}"


@lru_cache(maxsize=1)
def load_catalog(path: str = _DATA):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["name"], r.get("common", ""), float(r["ra_deg"]),
                             float(r["dec_deg"]), float(r.get("major_arcmin") or 0.0)))
            except (ValueError, KeyError):
                continue
    return rows


def _pixscale_arcsec(wcs) -> float:
    try:
        return float(np.sqrt(abs(np.linalg.det(wcs.pixel_scale_matrix))) * 3600.0)
    except Exception:
        return 0.0


def objects_in_field(wcs, shape, rows=None) -> list[CatalogObject]:
    """Catalogue objects that fall within — or, for large ones, OVERLAP — the
    frame, each with a pixel anchor for its label. An object whose centre is off
    the frame but whose angular size reaches into it (e.g. a big nebula filling
    the view, like NGC 7000) is still included: its `centered` flag is False and
    its label anchor is clamped to the frame edge so it stays visible."""
    rows = load_catalog() if rows is None else rows
    h, w = shape
    pixscale = _pixscale_arcsec(wcs)
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    out = []
    for name, common, ra, dec, major in rows:
        try:
            x, y = wcs.world_to_pixel(SkyCoord(ra * u.deg, dec * u.deg))
        except Exception:
            continue
        x = float(x)
        y = float(h - 1 - y) if FITS_Y_DOWN else float(y)   # -> top-row-first display
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        r_px = (major * 60.0 / 2.0) / pixscale if pixscale > 0 else 0.0  # half-extent in px
        if not (-r_px <= x < w + r_px and -r_px <= y < h + r_px):
            continue                                         # object doesn't reach the frame
        centered = 0 <= x < w and 0 <= y < h
        lx = min(max(x, _LABEL_MARGIN), w - _LABEL_MARGIN)   # clamp label into the frame
        ly = min(max(y, _LABEL_MARGIN), h - _LABEL_MARGIN)
        out.append(CatalogObject(_pretty_name(name), common, ra, dec, major, lx, ly, centered))
    return out


@lru_cache(maxsize=1)
def load_named_stars(path: str = _STARS):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["name"], float(r["ra_deg"]), float(r["dec_deg"]),
                             float(r.get("mag") or 99.0)))
            except (ValueError, KeyError):
                continue
    return rows


def named_stars_in_field(wcs, shape, rows=None) -> list[NamedStar]:
    """IAU-named bright stars (Deneb, Vega, …) that fall inside the frame, with a
    pixel position. Point sources, so only the in-frame ones are kept."""
    rows = load_named_stars() if rows is None else rows
    h, w = shape
    if not rows:
        return []
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    ras = np.array([r[1] for r in rows]); decs = np.array([r[2] for r in rows])
    coords = SkyCoord(ras * u.deg, decs * u.deg)
    xs, ys = wcs.world_to_pixel(coords)                 # vectorised projection
    out = []
    for (name, ra, dec, mag), x, y in zip(rows, np.atleast_1d(xs), np.atleast_1d(ys)):
        x = float(x)
        y = float(h - 1 - y) if FITS_Y_DOWN else float(y)
        if 0 <= x < w and 0 <= y < h and np.isfinite(x) and np.isfinite(y):
            out.append(NamedStar(name, ra, dec, mag, x, y))
    return out


def identify_target(objects: list[CatalogObject], shape) -> str:
    if not objects:
        return ""
    h, w = shape
    cx, cy = w / 2, h / 2
    best = max(objects, key=lambda o: (o.major_arcmin, -((o.x - cx) ** 2 + (o.y - cy) ** 2)))
    return f"{best.name} · {best.common}" if best.common else best.name
