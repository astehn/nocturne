"""Decides WHAT the annotation overlay draws and WHERE, as plain primitives in
image-pixel coordinates. Pure: no Qt, no rendering. Two adapters consume this —
the live Qt canvas and the burned export — so both draw identical content by
construction rather than by remembering to pass the same arguments."""
from __future__ import annotations

import math
from typing import NamedTuple

MIN_RADIUS_PX = 6.0          # below this a true-size circle is unreadable
DEFAULT_COLOUR = "#5cff5c"   # green: rare in astro images, so it never blends in


class Circle(NamedTuple):
    x: float
    y: float
    r: float
    colour: str
    dashed: bool = False


class Marker(NamedTuple):
    x: float
    y: float
    kind: str            # "star" | "compass"
    colour: str
    size: str = "star"


class Label(NamedTuple):
    text: str
    x: float
    y: float
    colour: str
    size: str = "secondary"
    priority: int = 0


class Leader(NamedTuple):
    x1: float
    y1: float
    x2: float
    y2: float
    colour: str
    screen_fixed: bool = False   # True only for a cosmetic overlay line (the compass
                                  # arrow) that must stay a constant on-screen length;
                                  # default False -- a leader connects two REAL image
                                  # positions (an object to its label, or the scale
                                  # bar's true angular length) and must scale/pan with
                                  # the image like any other measured geometry.


def circle_for(obj, pixscale_arcsec: float, colour: str = DEFAULT_COLOUR) -> Circle:
    """A ring at the object's TRUE angular half-extent, centred on its real
    projected position (obj.cx/cy) rather than the clamped label anchor — a big
    nebula whose centre is off-frame should draw the arc that crosses the frame.

    An unknown size (major_arcmin == 0) draws a DASHED minimum ring: 'we don't
    know how big this is' must look different from 'this is small'."""
    unknown = not obj.major_arcmin or pixscale_arcsec <= 0
    r = MIN_RADIUS_PX if unknown else (obj.major_arcmin * 60.0 / 2.0) / pixscale_arcsec
    return Circle(obj.cx, obj.cy, max(r, MIN_RADIUS_PX), colour, unknown)


def star_marker(star, colour: str = DEFAULT_COLOUR) -> Marker:
    """A star's position. The adapter draws FLANKING ticks, never a cross through
    the star, so the star itself stays visible. Brighter stars get a bigger mark."""
    size = "star_bright" if star.mag <= 3.0 else "star"
    return Marker(star.x, star.y, "star", colour, size)


_DENSITY = {                     # (min circle radius px, max star magnitude)
    "minimal": (None, 3.0),      # None = "named/Messier only", size ignored
    "balanced": (8.0, 4.5),
    "all": (0.0, 99.0),
}
_LABEL_GAP = 9.0                 # px between an object and its label


def _is_messier(obj) -> bool:
    """Driven by the catalogue's `messier` column, not a name convention — the
    bundled OpenNGC data keeps `name` as the NGC/IC designation (e.g. "NGC0224"),
    never an "M "-prefixed alias, so identity in target metadata / provenance
    reports stays stable. Objects that lack the field (e.g. constructed by
    older call sites) are simply not Messier, not an error."""
    return bool(getattr(obj, "messier", ""))


_TYPE_COLOURS = {
    "messier": "#b38cff",   # violet
    "emission": "#ff7a94",  # red-pink: HII, EmN, RfN, Cl+N, SNR, clusters
    "dark": "#e9edf5",      # white: dark nebulae
    "planetary": "#67e58b", # green
    "galaxy": "#ffab5e",    # orange
    "star": "#ffd75e",      # yellow
    "unknown": "#b9c2d0",   # grey
}
_TYPE_FAMILY = {
    "HII": "emission", "EmN": "emission", "RfN": "emission", "Cl+N": "emission",
    "SNR": "emission", "Neb": "emission", "OCl": "emission", "GCl": "emission",
    "DrkN": "dark", "PN": "planetary",
    "G": "galaxy", "GPair": "galaxy", "GTrpl": "galaxy", "GGroup": "galaxy",
    "Star": "star", "*Ass": "star",
}


def colour_for(obj, by_type: bool = False) -> str:
    """Default is the single green. By type, follows the palette astronomers see
    in Aladin/Astrometry.net renders, so it reads as familiar rather than novel."""
    if not by_type:
        return DEFAULT_COLOUR
    if _is_messier(obj):
        return _TYPE_COLOURS["messier"]
    fam = _TYPE_FAMILY.get(getattr(obj, "obj_type", "") or "", "unknown")
    return _TYPE_COLOURS[fam]


def priority_of(obj) -> int:
    """Higher survives. Density drops the lowest first, and placement puts the
    most significant labels down before the crowded ones fight for space."""
    if getattr(obj, "mag", None) is not None and not hasattr(obj, "major_arcmin"):
        return 10                                   # a NamedStar
    if _is_messier(obj):
        return 40
    return 30 if obj.common else 20


def filter_by_density(objects, stars, pixscale_arcsec, density="balanced"):
    """Drop the least significant content first, so what survives at a lower
    density is always the most meaningful subset rather than an arbitrary one."""
    min_r, max_mag = _DENSITY.get(density, _DENSITY["balanced"])
    if min_r is None:
        keep = [o for o in objects if _is_messier(o) or o.common]
    else:
        keep = [o for o in objects
                if o.common or circle_for(o, pixscale_arcsec).r >= min_r]
    keep.sort(key=priority_of, reverse=True)
    return keep, [s for s in stars if s.mag <= max_mag]


def _rect(x, y, w, h):
    return (x, y, x + w, y + h)


def _overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


# Fallback search directions once the four primary anchors all collide: every
# compass point, not just "further right and down" — so free space anywhere
# around the object can be found, not only in one quadrant.
_FALLBACK_DIRECTIONS = [(1, 0), (-1, 0), (0, -1), (0, 1),
                         (1, -1), (-1, -1), (1, 1), (-1, 1)]


def place_labels(items, shape, measure, colour=DEFAULT_COLOUR, ui_scale: float = 1.0):
    """Greedy placement in priority order. Anchors are tried right, left, above,
    then below; if all collide, the label is pushed outward — in all eight
    compass directions at increasing distance — until it finds free space, and
    a Leader connects it back to its object. `measure` is injected so this
    stays Qt-free — the Qt adapter passes a real font metric.

    `colour` is either a single colour string applied to every label (the
    original behaviour, still the default), or a callable `colour(item) ->
    str` so by-type colouring reaches the label and its leader too, not just
    the object's ring.

    `ui_scale` scales the fixed pixel spacing (`_LABEL_GAP` and the fallback
    search step) the same way `measure`'s caller is expected to scale text
    size -- so the gap between a label and its anchor grows/shrinks with the
    glyphs actually being reserved for. A mismatch here is exactly the PS-07
    class of bug: `measure` returning a box sized for text rendered BIGGER
    than the box reserves lets that bigger text overlap its neighbour even
    though this function found it a non-overlapping rectangle at build time."""
    resolve_colour = colour if callable(colour) else (lambda _it: colour)
    gap = _LABEL_GAP * ui_scale
    h, w = shape
    placed, labels, leaders = [], [], []
    for it in sorted(items, key=priority_of, reverse=True):
        # Prefer the Messier designation ("M 31") when the object has one —
        # that's how the user's reference images label these targets — else
        # fall back to the catalogue name; the common name is always appended.
        messier = getattr(it, "messier", "")
        designation = f"M {messier}" if messier else it.name
        text = f"{designation}  {it.common}".strip() if getattr(it, "common", "") else designation
        size = "primary" if priority_of(it) >= 40 else "secondary"
        tw, th = measure(text, size)
        # NOT `getattr(it, "x", it.cx)`: Python evaluates the default eagerly,
        # so `it.cx` would raise on a NamedStar (has x/y but no cx/cy) even
        # though "x" exists and the default is never used.
        ax = it.x if hasattr(it, "x") else it.cx
        ay = it.y if hasattr(it, "y") else it.cy
        candidates = [(ax + gap, ay - th / 2), (ax - gap - tw, ay - th / 2),
                      (ax - tw / 2, ay - gap - th), (ax - tw / 2, ay + gap)]
        for step in range(1, 9):                     # then search outward, all directions
            dist = gap + step * 18 * ui_scale
            for dx, dy in _FALLBACK_DIRECTIONS:
                candidates.append((ax - tw / 2 + dx * dist, ay - th / 2 + dy * dist))
        chosen = None
        for i, (lx, ly) in enumerate(candidates):
            # Clamp into the frame; if the label is wider/taller than the frame
            # itself, pin to 0 rather than letting the upper bound go negative
            # — starting inside and overflowing the far edge is the intended
            # behaviour for a label that genuinely cannot fit.
            lx = max(0.0, min(lx, max(0.0, w - tw)))
            ly = max(0.0, min(ly, max(0.0, h - th)))
            r = _rect(lx, ly, tw, th)
            if not any(_overlaps(r, p) for p in placed):
                chosen, displaced = (lx, ly), i >= 4
                break
        if chosen is None:
            continue                                  # no room: drop, never overlap
        lx, ly = chosen
        placed.append(_rect(lx, ly, tw, th))
        c = resolve_colour(it)
        labels.append(Label(text, lx, ly, c, size, priority_of(it)))
        if displaced:
            leaders.append(Leader(ax, ay, lx, ly + th / 2, c))
    return labels, leaders


class GridLine(NamedTuple):
    points: list
    colour: str
    label: str = ""


_GRID_STEPS_DEG = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]


def _fmt_ra(ra_deg: float) -> str:
    hours = (ra_deg % 360.0) / 15.0
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    h %= 24                          # a minute-carry at 23h60m must wrap to 0h, not 24h
    return f"{h}h{m:02d}m"


def _fmt_dec(dec_deg: float) -> str:
    sign = "-" if dec_deg < 0 else "+"
    d = abs(dec_deg)
    deg = int(d)
    minutes = int(round((d - deg) * 60))
    if minutes == 60:
        deg, minutes = deg + 1, 0
    return f"{sign}{deg}°{minutes:02d}′" if minutes else f"{sign}{deg}°"


def grid_lines(wcs, shape, colour: str) -> list:
    """Constant-RA and constant-Dec polylines clipped to the frame. Sampled
    rather than drawn straight, so the curvature of the projection shows."""
    if wcs is None:
        return []
    import numpy as np
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    from ..tools.astap import FITS_Y_DOWN

    h, w = shape
    try:
        corners = wcs.pixel_to_world(np.array([0, w - 1, 0, w - 1]),
                                     np.array([0, 0, h - 1, h - 1]))
        ras, decs = corners.ra.deg, corners.dec.deg
    except Exception:
        return []
    span = max(float(np.ptp(decs)), 0.01)
    step = min(_GRID_STEPS_DEG, key=lambda s: abs(s - span / 3.0))

    def project(ra_arr, dec_arr):
        x, y = wcs.world_to_pixel(SkyCoord(ra_arr * u.deg, dec_arr * u.deg))
        y = (h - 1 - y) if FITS_Y_DOWN else y
        return np.atleast_1d(x), np.atleast_1d(y)

    out = []
    dec_lo, dec_hi = float(np.min(decs)), float(np.max(decs))
    ra_lo, ra_hi = float(np.min(ras)), float(np.max(ras))
    for dec in np.arange(np.floor(dec_lo / step) * step, dec_hi + step, step):
        ra_s = np.linspace(ra_lo, ra_hi, 20)
        xs, ys = project(ra_s, np.full_like(ra_s, dec))
        pts = [(float(a), float(b)) for a, b in zip(xs, ys)
               if -1 <= a <= w and -1 <= b <= h]
        if len(pts) >= 2:
            out.append(GridLine(pts, colour, _fmt_dec(float(dec))))
    for ra in np.arange(np.floor(ra_lo / step) * step, ra_hi + step, step):
        dec_s = np.linspace(dec_lo, dec_hi, 20)
        xs, ys = project(np.full_like(dec_s, ra), dec_s)
        pts = [(float(a), float(b)) for a, b in zip(xs, ys)
               if -1 <= a <= w and -1 <= b <= h]
        if len(pts) >= 2:
            out.append(GridLine(pts, colour, _fmt_ra(float(ra))))
    return out


# Colours for the frame furniture (grid/compass/scale) are fixed, independent
# of `by_type` -- that toggle is about telling catalogue object TYPES apart,
# not the reference overlay drawn on top of them.
_GRID_COLOUR = "#6a7688"      # muted slate: visible without competing with object colours
_COMPASS_COLOUR = "#6aa8f2"   # bright blue, matches the pre-existing compass accent
_SCALE_COLOUR = "#e7ecf4"     # near-white, reads on both light and dark frame content

_MEASURE_PT = {"primary": 16.0, "secondary": 14.0, "star": 12.0, "star_bright": 14.0,
               "grid": 11.0, "compass": 17.0}


def _default_measure(text: str, size: str, ui_scale: float = 1.0) -> tuple[float, float]:
    """A pure (Qt-free) fallback text-size estimate, used only when a caller
    doesn't inject a real one. Good enough for headless/test use; a live Qt
    caller should pass actual font metrics for pixel-exact label placement.

    `ui_scale` must match the scale the CONSUMING adapter actually renders
    text at -- `place_labels` reserves non-overlap rectangles from this
    return value, so if the export adapter later draws text bigger than what
    was reserved here, labels overlap in the export even though the live
    preview (which renders at the unscaled size this defaults to) looks
    clean. See `build_layout_for`'s `ui_scale` param."""
    pt = _MEASURE_PT.get(size, _MEASURE_PT["secondary"]) * ui_scale
    return len(text) * pt * 0.62, pt * 1.3


def _compass_primitives(wcs, shape, ui_scale: float = 1.0) -> list:
    from .annotate import compass_angles
    north, _east = compass_angles(wcs, shape)
    h, w = shape
    ax, ay = w - 120.0 * ui_scale, 120.0 * ui_scale
    rad = math.radians(north)
    tx, ty = ax + 60.0 * ui_scale * math.cos(rad), ay + 60.0 * ui_scale * math.sin(rad)
    lx = ax + 74.0 * ui_scale * math.cos(rad) - 6.0 * ui_scale
    ly = ay + 74.0 * ui_scale * math.sin(rad) - 7.0 * ui_scale
    return [
        Marker(ax, ay, "compass", _COMPASS_COLOUR, "grid"),
        Leader(ax, ay, tx, ty, _COMPASS_COLOUR, screen_fixed=True),   # cosmetic HUD arrow
        Label("N", lx, ly, _COMPASS_COLOUR, "compass"),
    ]


def _scale_bar_primitives(pixscale_arcsec: float, shape, ui_scale: float = 1.0) -> list:
    from .annotate import scale_bar
    h, w = shape
    length_px, text = scale_bar(pixscale_arcsec, w)   # a TRUE measured length -- never scaled
    if length_px <= 0:
        return []
    bx, by = 90.0 * ui_scale, h - 90.0 * ui_scale
    return [
        Leader(bx, by, bx + length_px, by, _SCALE_COLOUR),
        Label(text, bx, by - 24.0 * ui_scale, _SCALE_COLOUR, "secondary"),
    ]


def build_layout_for(objects, stars, wcs, shape, pixscale, layers, density,
                      measure=None, ui_scale: float = 1.0) -> list:
    """Assembles the FULL primitive list the overlay draws: circles + labels +
    leaders for catalogue objects, flanking-tick markers for named stars, grid
    lines, and the compass/scale bar -- all as plain Circle/Marker/Label/
    Leader/GridLine values in image-pixel coordinates. Pure: no Qt.

    Both the live Qt canvas and the burned export consume this SAME function,
    so they draw identical CONTENT by construction rather than by remembering
    to pass the same arguments twice. Their PLACEMENT can legitimately
    differ, via `ui_scale` -- see below -- and that is by design, not a gap:
    once two adapters render text at different physical sizes, identical
    pixel positions were never achievable; content parity is the guarantee
    that matters and is preserved regardless of `ui_scale`.

    `layers` is a dict of booleans keyed "objects", "stars", "grid", "compass",
    "scale", "by_type" -- missing keys default to off. `measure` is forwarded
    to `place_labels`; pass real font metrics for pixel-exact placement, or
    leave it as the pure fallback for headless/test use.

    `ui_scale` is the factor the CONSUMING adapter will render text/glyph
    sizes at, relative to the live adapter's constant on-screen point sizes
    (the live adapter always passes the default, 1.0). It scales BOTH the
    default measure's text-box estimate AND every fixed pixel offset that
    `place_labels`/`_compass_primitives`/`_scale_bar_primitives` use to
    position things relative to those boxes (`_LABEL_GAP`, the fallback
    search step, the compass anchor/arrow/label offsets, the scale bar's
    anchor and label gap -- never a TRUE measured quantity like a Circle's
    radius or the scale bar's own length, which stay in real image pixels).
    Skipping this was PS-07 recurring one level up: an export that renders
    text bigger than what was RESERVED for it at layout time can overlap
    labels that the (unscaled) live preview shows cleanly separated, even
    though both consumed the identical primitive list.

    Each object's colour is resolved individually via `colour_for(obj,
    by_type=...)` and carried through to its circle, label AND leader -- a
    single shared colour would make by-type colouring invisible on the labels.
    Named stars get the type palette's `"star"` (yellow) colour under the same
    toggle, on their marker AND their name label; both fall back to the plain
    default colour when `by_type` is off.

    Object and star labels are placed through a SINGLE `place_labels` call so
    a star's name competes for space (and gets a leader when displaced) in
    the same collision-avoidance pass as every DSO label, rather than being
    positioned independently and risking an overlap."""
    if measure is None:
        measure = lambda text, size: _default_measure(text, size, ui_scale)
    by_type = layers.get("by_type", False)

    kept_objs, kept_stars = filter_by_density(objects, stars, pixscale, density)
    if not layers.get("objects", False):
        kept_objs = []
    if not layers.get("stars", False):
        kept_stars = []

    prims: list = []

    obj_colour = {id(o): colour_for(o, by_type=by_type) for o in kept_objs}
    for o in kept_objs:
        prims.append(circle_for(o, pixscale, obj_colour[id(o)]))

    star_colour = _TYPE_COLOURS["star"] if by_type else DEFAULT_COLOUR
    for s in kept_stars:
        prims.append(star_marker(s, star_colour))

    item_colour = dict(obj_colour)
    item_colour.update({id(s): star_colour for s in kept_stars})
    labels, leaders = place_labels(kept_objs + kept_stars, shape, measure,
                                    colour=lambda it: item_colour[id(it)], ui_scale=ui_scale)
    prims.extend(labels)
    prims.extend(leaders)

    if layers.get("grid", False):
        prims.extend(grid_lines(wcs, shape, _GRID_COLOUR))

    if layers.get("compass", False) and wcs is not None:
        prims.extend(_compass_primitives(wcs, shape, ui_scale))

    if layers.get("scale", False) and pixscale > 0:
        prims.extend(_scale_bar_primitives(pixscale, shape, ui_scale))

    return prims
