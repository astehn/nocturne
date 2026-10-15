"""Decides WHAT the annotation overlay draws and WHERE, as plain primitives in
image-pixel coordinates. Pure: no Qt, no rendering. Two adapters consume this —
the live Qt canvas and the burned export — so both draw identical content by
construction rather than by remembering to pass the same arguments."""
from __future__ import annotations

import math
from typing import NamedTuple

MIN_RADIUS_PX = 6.0          # below this a true-size circle is unreadable
_MAX_CIRCLE_FRAMES = 0.75    # drop rings larger than this * the frame diagonal

# The look approved 2026-10-15 (spec 2026-10-15-solve-restyle, mockup
# render_proposed.py), after his PixInsight-style references. Colours are
# "#RRGGBB", or "#AARRGGBB" where the primitive is meant to be translucent —
# the form QColor(str) reads directly, so the alpha travels with the colour.
MAJOR_COLOUR = "#f4877c"     # soft salmon: Messier, NGC, IC, anything with a common name
MINOR_COLOUR = "#eef1f6"     # white: LDN, Barnard, Sh2, vdB
STAR_COLOUR = "#ffd447"      # yellow: named stars
GRID_LINE_COLOUR = "#46ebf0f8"   # white at 70/255 = 27%: present, never competing
GRID_TEXT_COLOUR = "#e6e6ebf2"
FURNITURE_TEXT_COLOUR = "#dceef1f6"


def _alpha(colour: str, a: int) -> str:
    return f"#{a:02x}{colour[1:]}"


# Rings are thin and slightly see-through in their label's colour; the minor
# tier a little fainter, as in the mockup.
_RING_COLOUR = {"major": _alpha(MAJOR_COLOUR, 200), "minor": _alpha(MINOR_COLOUR, 170)}
_LABEL_COLOUR = {"major": MAJOR_COLOUR, "minor": MINOR_COLOUR, "star": STAR_COLOUR}
_STAR_MARK_COLOUR = _alpha(STAR_COLOUR, 235)
_COMPASS_COLOUR = _alpha(MINOR_COLOUR, 200)
_SCALE_COLOUR = _alpha(MINOR_COLOUR, 210)

# Gapped crosshair of a named star, in REFERENCE px (gap from the star to where
# an arm starts, arm length). Renderers draw it at reference px x their own
# scale (1 on screen, scale_for(shape) in the export); the layout reserves it
# at x ui_scale, so a name starts past the arm. Mockup: 9/11 for every star
# (both keys kept so Marker.size stays a valid key for old callers).
STAR_RETICLE = {"star": (9.0, 11.0), "star_bright": (9.0, 11.0)}

# Text size classes, in points at the 1200 px reference (the mockup's PT).
# The layout only ever sees them through `measure`; the renderers own the
# fonts. Task 2's renderers and Qt measure should read this table.
LABEL_PT = {"major": 21.0, "major_common": 16.5, "minor": 13.0, "star": 14.0,
            "grid": 14.0, "furniture": 13.0}


class Circle(NamedTuple):
    x: float
    y: float
    r: float
    colour: str
    dashed: bool = False
    tier: str = ""       # "major" | "minor": lets a renderer pick the stroke


class Marker(NamedTuple):
    x: float
    y: float
    kind: str            # "star" (gapped crosshair, see STAR_RETICLE)
    colour: str
    size: str = "star"   # "star" | "star_bright": a key of STAR_RETICLE


class Label(NamedTuple):
    """A placed block of text. (x, y) is the top-left of the WHOLE block and
    (w, h) the box the layout reserved for it, both in image px.

    One line: draw `text` (or `parts`) left-aligned at (x, y) in `size`.
    Two lines (`sub` set): `text` in `size` on top, `sub` in `sub_size` under
    it, each centred horizontally in the block's width `w`.
    `parts`: when not empty, the line is drawn run by run, each (run, raised);
    a raised run is set small and lifted (the h and m of 2ʰ40ᵐ). The runs
    always join to exactly `text`, which stays the plain fallback."""
    text: str
    x: float
    y: float
    colour: str
    size: str = "minor"
    priority: int = 0
    tip: str = ""        # plain words for the canvas tooltip; the burned export ignores it
    sub: str = ""
    sub_size: str = ""
    tier: str = ""       # "major" | "minor" | "star" | "grid" | "furniture"
    parts: tuple = ()
    w: float = 0.0
    h: float = 0.0


class Leader(NamedTuple):
    """A straight line between two image positions. Since the restyle only the
    frame furniture uses it (compass arrow, scale bar and its end ticks):
    object labels never get one. Every coordinate is image px already sized
    for the consumer through ui_scale, so nothing the layout emits is
    screen_fixed any more; the field stays for old callers."""
    x1: float
    y1: float
    x2: float
    y2: float
    colour: str
    screen_fixed: bool = False


def circle_for(obj, pixscale_arcsec: float, colour: str = _RING_COLOUR["major"],
               tier: str = "") -> Circle:
    """A ring at the object's TRUE angular half-extent, centred on its real
    projected position (obj.cx/cy) rather than the clamped label anchor — a big
    nebula whose centre is off-frame should draw the arc that crosses the frame.

    An unknown size (major_arcmin == 0) draws a DASHED minimum ring: 'we don't
    know how big this is' must look different from 'this is small'."""
    unknown = not obj.major_arcmin or pixscale_arcsec <= 0
    r = MIN_RADIUS_PX if unknown else (obj.major_arcmin * 60.0 / 2.0) / pixscale_arcsec
    return Circle(obj.cx, obj.cy, max(r, MIN_RADIUS_PX), colour, unknown, tier)


def star_marker(star, colour: str = _STAR_MARK_COLOUR) -> Marker:
    """A star's position. The adapter draws a GAPPED crosshair, never a cross
    through the star, so the star itself stays visible. Brighter stars get a
    bigger mark."""
    size = "star_bright" if star.mag <= 3.0 else "star"
    return Marker(star.x, star.y, "star", colour, size)


# Star magnitude cuts, loosened after real-frame testing: a 2-3 degree field
# holds very few bright stars, so the original 4.5 limit meant "Named stars"
# showed nothing at the default density even where a designation existed
# (NGC 7000's field has exactly one, 57 Cyg at mag 4.78). 6.0 is roughly the
# naked-eye limit and is what makes the toggle do something.
_DENSITY = {                     # (min circle radius px, max star magnitude)
    "minimal": (None, 4.5),      # None = "named/Messier only", size ignored
    "balanced": (8.0, 6.0),
    "all": (0.0, 99.0),
}


def designation(obj) -> str:
    """How an object should be NAMED to a human: "M 31", not "NGC 224".

    The one place this is decided. It was previously inline in the overlay's
    label builder, so the overlay said "M 31  Andromeda Galaxy" while the object
    list and the solved-target line both said "NGC 224" — three surfaces naming
    the same object three ways, in the same window. Spotted on a real M 31
    capture 2026-08-01.

    Messier wins because that is what people call these objects, and what the
    annotated references we matched use. Everything else keeps its catalogue
    name. Duck-typed like the rest of this module so it works on a NamedStar
    (no `messier` attribute) as readily as a CatalogObject.
    """
    messier = getattr(obj, "messier", "")
    return f"M {messier}" if messier else obj.name


def _is_messier(obj) -> bool:
    """Driven by the catalogue's `messier` column, not a name convention — the
    bundled OpenNGC data keeps `name` as the NGC/IC designation (e.g. "NGC0224"),
    never an "M "-prefixed alias, so identity in target metadata / provenance
    reports stays stable. Objects that lack the field (e.g. constructed by
    older call sites) are simply not Messier, not an error."""
    return bool(getattr(obj, "messier", ""))


_MAJOR_PREFIXES = ("NGC", "IC")


def tier_of(obj) -> str:
    """Two tiers, like the reference: what people name (Messier, NGC, IC, or
    anything with a common name) is major; the survey catalogues (LDN,
    Barnard, Sh2, vdB) are minor. Replaces "Colour by type" (ruled 2026-10-15)."""
    if not hasattr(obj, "major_arcmin"):
        return "star"
    if _is_messier(obj) or getattr(obj, "common", "") or obj.name.startswith(_MAJOR_PREFIXES):
        return "major"
    return "minor"


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


class GridLine(NamedTuple):
    points: list
    colour: str
    label: str = ""      # grid_lines() fills it; build_layout_for emits it as a Label instead
    tip: str = ""        # what the label's coordinate is, in words (canvas tooltip only)
    parts: tuple = ()    # RA notation runs, see ra_parts


def _ra_tip(label: str) -> str:
    return (f"{label} — right ascension: the sky's east–west coordinate. It is counted "
            "in hours because the sky turns once a day: 24 hours make the full circle, "
            "so 1 hour is 15 degrees.")


def _dec_tip(label: str) -> str:
    return (f"{label} — declination: the sky's north–south coordinate, like latitude "
            "on Earth. 0° is the celestial equator, +90° the north celestial pole.")


_GRID_STEPS_DEG = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]


def ra_parts(ra_deg: float) -> tuple:
    """2ʰ40ᵐ as runs for a renderer: (text, raised). Whole hours drop the
    minutes ("2ʰ"), as the reference charts do. The Unicode ʰᵐ were tried in
    the mockup and are too thin to read on a nebula; a raised small h/m is not."""
    hours = (ra_deg % 360.0) / 15.0
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    h %= 24                          # a minute-carry at 23h60m must wrap to 0h, not 24h
    parts = ((str(h), False), ("h", True))
    return parts + ((f"{m:02d}", False), ("m", True)) if m else parts


def _fmt_ra(ra_deg: float) -> str:
    """Plain form of ra_parts ("2h40m", "2h"): the tip's wording and the fallback."""
    return "".join(t for t, _ in ra_parts(ra_deg))


def _fmt_dec(dec_deg: float) -> str:
    sign = "−" if dec_deg < 0 else "+"   # U+2212: a real minus, as typeset
    d = abs(dec_deg)
    deg = int(d)
    minutes = int(round((d - deg) * 60))
    if minutes == 60:
        deg, minutes = deg + 1, 0
    if deg == 0 and minutes == 0:
        sign = "+"
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
            out.append(GridLine(pts, colour, _fmt_dec(float(dec)), _dec_tip(_fmt_dec(float(dec)))))
    for ra in np.arange(np.floor(ra_lo / step) * step, ra_hi + step, step):
        dec_s = np.linspace(dec_lo, dec_hi, 20)
        xs, ys = project(np.full_like(dec_s, ra), dec_s)
        pts = [(float(a), float(b)) for a, b in zip(xs, ys)
               if -1 <= a <= w and -1 <= b <= h]
        if len(pts) >= 2:
            out.append(GridLine(pts, colour, _fmt_ra(float(ra)), _ra_tip(_fmt_ra(float(ra))),
                               ra_parts(float(ra))))
    return out


def _rect(x, y, w, h):
    return (x, y, x + w, y + h)


def _overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _free(r, occupied) -> bool:
    return not any(_overlaps(r, o) for o in occupied)


# All offsets below are reference px at ui_scale 1, from the approved mockup
# (render_proposed.py), judged by eye against his PixInsight examples.
_MARGIN = 14.0          # labels keep half of this from the frame edge
_GAP = 6.0              # between a ring and the label set against it
_BIG_CIRCLE_FRAC = 0.12 # a ring wider than this * the short side takes its label inside
_INNER_OFFSET = 30.0    # the inside-a-big-ring fallbacks, above / below the centre
_INNER_RIM_R = 40.0     # rings larger than this also try their inner rim
_OBSTACLE_R = 30.0      # in-frame rings smaller than this block other labels
_PAD = 2.0              # breathing room kept round every placed label


def _measure_block(measure, text, size, sub="", sub_size=""):
    """(w, h) of a one- or two-line label through the injected one-line
    measure — the measure contract stays measure(text, size) -> (w, h)."""
    w1, h1 = measure(text, size)
    if not sub:
        return w1, h1
    w2, h2 = measure(sub, sub_size)
    return max(w1, w2), h1 + h2


def _clamp_into(x, y, tw, th, shape, inset):
    h, w = shape
    x = min(max(x, inset), w - inset - tw)
    y = min(max(y, inset), h - inset - th)
    return x, y


def _fits(tw, th, shape, inset) -> bool:
    h, w = shape
    return tw <= w - 2 * inset and th <= h - 2 * inset


def merge_aliases(objects, pixscale_arcsec):
    """One label per physical object: catalogue entries that share a common
    name and overlap on the sky (centres within the larger ring) collapse
    into the most significant entry — M 16 and IC 4703 are both "Eagle
    Nebula". Returns [(representative, [representative, *aliases])]. Entries
    without a common name are never merged: two anonymous neighbours are two
    objects. At equal priority an NGC/IC name leads a survey one, whatever the
    sizes: the Soul is "IC 1848 · Sh 2-199", the name people use first."""
    order = sorted(objects, key=lambda o: (priority_of(o), o.name.startswith(_MAJOR_PREFIXES),
                                           o.major_arcmin), reverse=True)
    used, out = set(), []
    for o in order:
        if id(o) in used:
            continue
        used.add(id(o))
        group = [o]
        if o.common:
            r_o = circle_for(o, pixscale_arcsec).r
            for p in order:
                if id(p) in used or p.common != o.common:
                    continue
                if math.hypot(p.cx - o.cx, p.cy - o.cy) <= max(r_o, circle_for(p, pixscale_arcsec).r):
                    group.append(p)
                    used.add(id(p))
        out.append((o, group))
    return out


def _rim_candidates(ax, ay, rr, tw, th):
    """Around a ring at radius rr: right, left, the four diagonals, top, bottom.
    Each box touches the rim at its own near edge, so the text sits against
    the circle rather than on it."""
    out = []
    for ang in (0, 180, -40, 40, -140, 140, -90, 90):
        a = math.radians(ang)
        ex, ey = ax + rr * math.cos(a), ay + rr * math.sin(a)
        if ang in (0, -40, 40):
            out.append((ex, ey - th / 2))
        elif ang in (180, -140, 140):
            out.append((ex - tw, ey - th / 2))
        elif ang == -90:
            out.append((ex - tw / 2, ey - th))
        else:
            out.append((ex - tw / 2, ey))
    return out


def _inner_rim_candidates(ax, ay, rr, tw, th):
    return [(ax - tw / 2, ay - rr), (ax - tw / 2, ay + rr - th),
            (ax + rr - tw, ay - th / 2), (ax - rr, ay - th / 2)]


def _contains(box, x, y) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _rings_blocking(rings, x, y) -> list:
    """Small-ring obstacle boxes that block a label anchored at (x, y): every
    one except those the anchor itself sits in. An object inside another's
    ring (LDN 1359 in NGC 896's, vdB 88 in Sh 2-293's) would otherwise find
    every candidate "taken" and lose its label; two coincident rings would
    drop both."""
    return [b for b in rings if not _contains(b, x, y)]


def _covers_disc(r, disc) -> bool:
    """Does box r reach inside the disc (cx, cy, radius)? Its closest point to
    the centre decides."""
    cx, cy, rad = disc
    nx, ny = min(max(cx, r[0]), r[2]), min(max(cy, r[1]), r[3])
    return math.hypot(nx - cx, ny - cy) < rad


def _place_block(cands, tw, th, shape, inset, occupied, pad, blockers=(), own_disc=None):
    """First candidate that is free once clamped into the frame, or None — the
    dropped-label rule: never a leader, never an overlap. `own_disc`: the
    label's own small ring, which the clamp at a frame edge can push it onto
    (B 349 and LDN 931 by NGC 7000's right edge)."""
    if not _fits(tw, th, shape, inset):
        return None
    for lx, ly in cands:
        lx, ly = _clamp_into(lx, ly, tw, th, shape, inset)
        r = _rect(lx, ly, tw, th)
        if own_disc is not None and _covers_disc(r, own_disc):
            continue
        if _free(r, occupied) and _free(r, blockers):
            occupied.append((lx - pad, ly - pad, lx + tw + pad, ly + th + pad))
            return lx, ly
    return None


def _object_labels(groups, shape, pixscale, measure, u, occupied, rings=()):
    h, w = shape
    inset, gap, pad = _MARGIN * u / 2, _GAP * u, _PAD * u
    max_r = _MAX_CIRCLE_FRAMES * math.hypot(h, w)
    order = sorted(groups, key=lambda g: (tier_of(g[0]) == "major", priority_of(g[0]),
                                          g[0].major_arcmin), reverse=True)
    labels = []
    for o, grp in order:
        tier = tier_of(o)
        text = " · ".join(dict.fromkeys(designation(g) for g in grp))
        size = tier
        sub = o.common or ""
        sub_size = "major_common" if sub and tier == "major" else (size if sub else "")
        tw, th = _measure_block(measure, text, size, sub, sub_size)
        c = circle_for(o, pixscale)
        r = c.r if c.r <= max_r else 0.0
        big = c.r > _BIG_CIRCLE_FRAC * min(h, w)
        if not (0 <= o.cx < w and 0 <= o.cy < h):
            r, big = 0.0, False              # off-frame centre: label by the clamped anchor
        ax, ay = o.x, o.y
        cands = []
        if big:
            cands += [(ax - tw / 2, ay - th / 2), (ax - tw / 2, ay - th - _INNER_OFFSET * u),
                      (ax - tw / 2, ay + _INNER_OFFSET * u)]
        cands += _rim_candidates(ax, ay, r + gap, tw, th)
        blockers = _rings_blocking(rings, ax, ay)
        # Outside the rim the label must stay off its own ring, which the frame
        # clamp can push it onto; the inner rim is inside it on purpose.
        own = (c.x, c.y, r) if r > 0 and not big else None
        spot = _place_block(cands, tw, th, shape, inset, occupied, pad, blockers, own)
        if spot is None and r > _INNER_RIM_R * u:
            spot = _place_block(_inner_rim_candidates(ax, ay, r - gap, tw, th), tw, th, shape,
                                inset, occupied, pad, blockers)
        if spot is None:
            continue
        labels.append(Label(text, spot[0], spot[1], _LABEL_COLOUR[tier], size, priority_of(o),
                            sub=sub, sub_size=sub_size, tier=tier, w=tw, h=th))
    return labels


def _star_reach(star, u) -> float:
    gap, arm = STAR_RETICLE[star_marker(star).size]
    return (gap + arm) * u


def _star_labels(stars, shape, measure, u, occupied, rings=()):
    inset, pad = _MARGIN * u / 2, _PAD * u
    labels = []
    for st in sorted(stars, key=lambda s: s.mag):
        tw, th = measure(st.name, "star")
        # Past the arm by the same gap a label keeps from a ring (the mockup's).
        cands = _rim_candidates(st.x, st.y, _star_reach(st, u) + (_PAD + _GAP) * u, tw, th)
        spot = _place_block(cands, tw, th, shape, inset, occupied, pad,
                            _rings_blocking(rings, st.x, st.y))
        if spot is not None:
            labels.append(Label(st.name, spot[0], spot[1], STAR_COLOUR, "star", priority_of(st),
                                tier="star", w=tw, h=th))
    return labels


def _point_along(pts, from_end: int, dist: float):
    seq = pts if from_end == 0 else pts[::-1]
    acc = 0.0
    for (x0, y0), (x1, y1) in zip(seq, seq[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if acc + seg >= dist:
            t = (dist - acc) / seg if seg else 0.0
            return x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        acc += seg
    return seq[-1]


def _nearest_edge(x, y, shape) -> str:
    h, w = shape
    d = {"left": x, "right": w - x, "top": y, "bottom": h - y}
    return min(d, key=d.get)


# RA lines run roughly up-down, so their labels read best on the bottom/top
# edge; Dec lines on the left/right — the reference charts' convention.
_EDGE_PREF = {True: ["bottom", "top", "left", "right"], False: ["left", "right", "top", "bottom"]}


def _dist_to_polyline(px, py, pts) -> float:
    best = math.inf
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        ll = dx * dx + dy * dy
        t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / ll))
        best = min(best, math.hypot(px - x0 - t * dx, py - y0 - t * dy))
    return best


def _place_grid_labels(lines, shape, measure, u, occupied, rings=()):
    """Each line's label ON the line just inside the frame, centred on the
    point a short way in from the end that meets the preferred edge; if that
    spot is taken the other end is tried, then the label is dropped. Clamped
    so it is never clipped by the frame edge — and an end where the clamp
    drags the label more than half its height off its line counts as taken
    (4% of labels sat up to 100 px off their line in a random sweep)."""
    inset, pad, margin = _MARGIN * u / 2, _PAD * u, _MARGIN * u
    labels = []
    for gl in lines:
        if not gl.label or len(gl.points) < 2:
            continue
        is_ra = bool(gl.parts)
        tw, th = measure(gl.label, "grid")
        pref = _EDGE_PREF[is_ra]
        ends = sorted((0, 1), key=lambda e: pref.index(
            _nearest_edge(*(gl.points[0] if e == 0 else gl.points[-1]), shape)))
        cands = []
        for end in ends:
            px, py = _point_along(gl.points, end, margin + 0.6 * max(tw, th))
            if not _fits(tw, th, shape, inset):
                break
            lx, ly = _clamp_into(px - tw / 2, py - th / 2, tw, th, shape, inset)
            if _dist_to_polyline(lx + tw / 2, ly + th / 2, gl.points) <= th / 2:
                cands.append((lx, ly))
        spot = _place_block(cands, tw, th, shape, inset, occupied, pad, rings)
        if spot is not None:
            labels.append(Label(gl.label, spot[0], spot[1], GRID_TEXT_COLOUR, "grid",
                                tip=gl.tip, tier="grid", parts=gl.parts, w=tw, h=th))
    return labels


def _default_measure(text: str, size: str, ui_scale: float = 1.0) -> tuple[float, float]:
    """A pure (Qt-free) fallback text-size estimate, used only when a caller
    doesn't inject a real one. Good enough for headless/test use; a live Qt
    caller should pass actual font metrics for pixel-exact label placement.

    `ui_scale` must match the scale the CONSUMING adapter actually renders
    text at -- the layout reserves non-overlap rectangles from this return
    value, so text drawn bigger than what was reserved overlaps in the
    export even though the live preview looks clean (PS-07)."""
    pt = LABEL_PT.get(size, LABEL_PT["minor"]) * ui_scale
    return len(text) * pt * 0.62, pt * 1.3


_N_TIP = ("North on the sky. In a normal (not mirrored) view with north up, east "
          "is to the left — the reverse of a map, because you look up at the sky "
          "rather than down at the ground.")


def _compass_primitives(wcs, shape, measure, u, occupied) -> list:
    """A thin arrow and an N in the top-right corner, which it owns."""
    from .annotate import compass_angles
    north, _east = compass_angles(wcs, shape)
    h, w = shape
    cx, cy, length = w - 70.0 * u, 70.0 * u, 38.0 * u
    rad = math.radians(north)
    tw, th = measure("N", "furniture")
    nx = cx + (length + 12.0 * u) * math.cos(rad) - tw / 2
    ny = cy + (length + 12.0 * u) * math.sin(rad) - th / 2
    occupied.append((cx - 60.0 * u, cy - 60.0 * u, cx + 60.0 * u, cy + 60.0 * u))
    return [Leader(cx, cy, cx + length * math.cos(rad), cy + length * math.sin(rad), _COMPASS_COLOUR),
            Label("N", nx, ny, FURNITURE_TEXT_COLOUR, "furniture", tip=_N_TIP,
                  tier="furniture", w=tw, h=th)]


def _scale_bar_primitives(pixscale_arcsec, shape, measure, u, occupied) -> list:
    """A thin bar with end ticks in the bottom-left corner, its length
    centred above it. The bar's length is TRUE (measured), never scaled."""
    from .annotate import scale_bar, scale_bar_arcsec, scale_bar_tip
    h, w = shape
    length, text = scale_bar(pixscale_arcsec, w)
    if length <= 0:
        return []
    bx, by, tick = 40.0 * u, h - 40.0 * u, 5.0 * u
    tw, th = measure(text, "furniture")
    tx, ty = bx + length / 2 - tw / 2, by - 10.0 * u - th
    occupied.append((bx - 10.0 * u, ty - 4.0 * u, bx + length + 10.0 * u, by + 10.0 * u))
    return [Leader(bx, by, bx + length, by, _SCALE_COLOUR),
            Leader(bx, by - tick, bx, by + tick, _SCALE_COLOUR),
            Leader(bx + length, by - tick, bx + length, by + tick, _SCALE_COLOUR),
            Label(text, tx, ty, FURNITURE_TEXT_COLOUR, "furniture",
                  tip=scale_bar_tip(scale_bar_arcsec(pixscale_arcsec, w)),
                  tier="furniture", w=tw, h=th)]


def build_layout_for(objects, stars, wcs, shape, pixscale, layers, density,
                     measure=None, ui_scale: float = 1.0) -> list:
    """The FULL primitive list the overlay draws, in image-pixel coordinates:
    Circle, Marker, Label, Leader (furniture only) and GridLine. Pure: no Qt.

    The live canvas and the burned export both consume this SAME function,
    so they draw identical content by construction. `ui_scale` is the factor
    the consumer renders text and glyphs at, relative to the reference sizes
    (1/zoom on the live canvas, annotation_render.scale_for in the export);
    every fixed offset scales with it, every TRUE size (a ring's radius, the
    scale bar's length, a grid line) does not. `measure(text, size)` must
    return the image-px box the consumer will paint at that scale.

    `layers`: booleans "objects", "stars", "grid", "compass", "scale";
    missing keys are off. A "by_type" key from old settings is accepted and
    ignored — the two tiers replaced colour by type (ruled 2026-10-15).

    Space is claimed in the mockup's order, so what matters most is never
    the one dropped: frame furniture owns its corners, then small in-frame
    rings, grid labels, star reticles, object labels (majors first) and last
    star names. A label with no free spot is dropped — the Objects-in-field
    list still names it."""
    if measure is None:
        measure = lambda text, size: _default_measure(text, size, ui_scale)
    u = ui_scale
    h, w = shape

    kept_objs, kept_stars = filter_by_density(objects, stars, pixscale, density)
    if not layers.get("objects", False):
        kept_objs = []
    if not layers.get("stars", False):
        kept_stars = []

    prims: list = []
    occupied: list = []
    rings: list = []          # small in-frame rings, kept apart: see _rings_blocking

    furniture = []
    if layers.get("compass", False) and wcs is not None:
        furniture += _compass_primitives(wcs, shape, measure, u, occupied)
    if layers.get("scale", False) and pixscale > 0:
        furniture += _scale_bar_primitives(pixscale, shape, measure, u, occupied)

    # A circle far larger than the frame marks nothing useful — Sh2-109's
    # catalogued 18 degrees on a 3-degree field is an arc across the whole
    # image. Keep the object's LABEL (it is genuinely in the field) and drop
    # the ring beyond this multiple of the frame diagonal.
    max_r = _MAX_CIRCLE_FRAMES * math.hypot(h, w)
    groups = merge_aliases(kept_objs, pixscale)
    for rep, grp in groups:
        tier = tier_of(rep)
        for o in grp:
            c = circle_for(o, pixscale, _RING_COLOUR[tier], tier)
            if c.r <= max_r:
                prims.append(c)
            if c.r < _OBSTACLE_R * u and 0 <= o.cx < w and 0 <= o.cy < h:
                e = c.r + 3.0 * u
                rings.append((c.x - e, c.y - e, c.x + e, c.y + e))

    grid_labels = []
    if layers.get("grid", False):
        lines = grid_lines(wcs, shape, GRID_LINE_COLOUR)
        grid_labels = _place_grid_labels(lines, shape, measure, u, occupied, rings)
        prims.extend(gl._replace(label="", tip="", parts=()) for gl in lines)

    for s in kept_stars:
        prims.append(star_marker(s))
        e = _star_reach(s, u)
        occupied.append((s.x - e, s.y - e, s.x + e, s.y + e))

    prims.extend(grid_labels)
    prims.extend(_object_labels(groups, shape, pixscale, measure, u, occupied, rings))
    prims.extend(_star_labels(kept_stars, shape, measure, u, occupied, rings))
    prims.extend(furniture)
    return prims
