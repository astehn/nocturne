"""Bundled OpenNGC deep-sky catalogue: load rows and project them through a
plate-solved WCS to place annotation labels."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..tools.astap import FITS_Y_DOWN

_DATA = os.path.join(os.path.dirname(__file__), "..", "data", "openngc.csv")


@dataclass
class CatalogObject:
    name: str
    common: str
    ra_deg: float
    dec_deg: float
    major_arcmin: float
    x: float
    y: float


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


def objects_in_field(wcs, shape, rows=None) -> list[CatalogObject]:
    rows = load_catalog() if rows is None else rows
    h, w = shape
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
        if 0 <= x < w and 0 <= y < h and np.isfinite(x) and np.isfinite(y):
            out.append(CatalogObject(name, common, ra, dec, major, x, y))
    return out


def identify_target(objects: list[CatalogObject], shape) -> str:
    if not objects:
        return ""
    h, w = shape
    cx, cy = w / 2, h / 2
    best = max(objects, key=lambda o: (o.major_arcmin, -((o.x - cx) ** 2 + (o.y - cy) ** 2)))
    return f"{best.name} · {best.common}" if best.common else best.name
