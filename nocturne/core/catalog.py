"""Bundled OpenNGC deep-sky catalogue: load rows and project them through a
plate-solved WCS to place annotation labels."""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..tools.astap import FITS_Y_DOWN

# Resolve via Path.resolve() (like ui/icons.py) so the ".." collapses to a real
# path. A raw os.path.join(..., "..", "data", ...) leaves a "core/../data" that
# the OS can't traverse in the PyInstaller bundle — nocturne/core/ isn't a real
# directory there (the code lives in the PYZ archive) — so open() raised ENOENT.
_DATA = str(Path(__file__).resolve().parent.parent / "data" / "openngc.csv")
_NAMES = Path(__file__).resolve().parent.parent / "data" / "common_names.csv"
_STARS = str(Path(__file__).resolve().parent.parent / "data" / "named_stars.csv")
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
    cx: float = 0.0             # TRUE projected centre; may be outside the frame
    cy: float = 0.0             # (x/y above are the label anchor, clamped inside)
    obj_type: str = ""          # OpenNGC classification, e.g. "G", "HII", "PN"
    minor_arcmin: float = 0.0   # angular minor axis; 0.0 if unknown
    pos_angle: float = 0.0      # position angle in degrees; 0.0 if unknown
    messier: str = ""           # Messier number as a string ("31"), empty if none


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
@lru_cache(maxsize=1)
def _curated_names() -> dict:
    """Colloquial names for objects whose catalogues carry none.

    Kept OUT of openngc.csv on purpose. That file is regenerated wholesale by
    scripts/build_catalog.py + fetch_extra_catalogs.py, so anything hand-written
    into it is lost on the next rebuild. Applied here instead, where it survives.

    Only fills a BLANK common name — a name the source catalogue supplies always
    wins, so this can never override real data."""
    out = {}
    if not _NAMES.exists():
        return out
    with open(_NAMES, newline="") as f:
        for r in csv.DictReader(line for line in f if not line.startswith("#")):
            d, c = (r.get("designation") or "").replace(" ", ""), (r.get("common") or "").strip()
            if d and c:
                out[d] = c
    return out


def load_catalog(path: str = _DATA):
    curated = _curated_names()
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                common = r.get("common", "").strip() or curated.get(
                    r["name"].replace(" ", ""), "")
                rows.append((r["name"], common, float(r["ra_deg"]),
                             float(r["dec_deg"]), float(r.get("major_arcmin") or 0.0),
                             r.get("type", ""), float(r.get("minor_arcmin") or 0.0),
                             float(r.get("pos_angle") or 0.0), r.get("messier", "")))
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
    for row in rows:
        # Rows are 5-tuples in older call sites / tests, 9-tuples (with type,
        # minor axis, position angle, Messier number) from the bundled catalog.
        name, common, ra, dec, major = row[0], row[1], row[2], row[3], row[4]
        obj_type = row[5] if len(row) > 5 else ""
        minor = row[6] if len(row) > 6 else 0.0
        pos_angle = row[7] if len(row) > 7 else 0.0
        messier = row[8] if len(row) > 8 else ""
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
        out.append(CatalogObject(_pretty_name(name), common, ra, dec, major,
                                 lx, ly, centered, x, y,
                                 obj_type=obj_type, minor_arcmin=minor,
                                 pos_angle=pos_angle, messier=messier))
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
    """The object the frame is most plausibly OF.

    Not simply the largest: once Sharpless and Lynds entries joined the
    catalogue, an NGC 7000 frame reported 'Sh 2109' — a 18-degree diffuse
    complex that merely overlaps the field. Rank by significance instead —
    a Messier or common-named object beats an anonymous survey designation —
    and only then by size and centrality."""
    if not objects:
        return ""
    h, w = shape
    cx, cy = w / 2, h / 2

    def rank(o):
        centred = 0 <= o.x < w and 0 <= o.y < h
        # An object far larger than the frame says little about what was imaged.
        sane_size = o.major_arcmin if o.major_arcmin <= 3.0 * (h * w) ** 0.5 else 0.0
        return (bool(getattr(o, "messier", "")), bool(o.common), centred,
                sane_size, -((o.x - cx) ** 2 + (o.y - cy) ** 2))

    from .annotation_layout import designation
    best = max(objects, key=rank)
    name = designation(best)        # "M 31", not "NGC 224" — same as the overlay
    return f"{name} · {best.common}" if best.common else name
