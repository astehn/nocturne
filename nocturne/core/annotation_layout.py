"""Decides WHAT the annotation overlay draws and WHERE, as plain primitives in
image-pixel coordinates. Pure: no Qt, no rendering. Two adapters consume this —
the live Qt canvas and the burned export — so both draw identical content by
construction rather than by remembering to pass the same arguments."""
from __future__ import annotations

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
    return obj.name.upper().startswith("M ")


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


def place_labels(items, shape, measure, colour=DEFAULT_COLOUR):
    """Greedy placement in priority order. Anchors are tried right, left, above,
    then below; if all collide, the label is pushed outward until it finds free
    space and a Leader connects it back to its object. `measure` is injected so
    this stays Qt-free — the Qt adapter passes a real font metric."""
    h, w = shape
    placed, labels, leaders = [], [], []
    for it in sorted(items, key=priority_of, reverse=True):
        text = f"{it.name}  {it.common}".strip() if getattr(it, "common", "") else it.name
        size = "primary" if priority_of(it) >= 40 else "secondary"
        tw, th = measure(text, size)
        ax, ay = getattr(it, "x", it.cx), getattr(it, "y", it.cy)
        candidates = [(ax + _LABEL_GAP, ay - th / 2), (ax - _LABEL_GAP - tw, ay - th / 2),
                      (ax - tw / 2, ay - _LABEL_GAP - th), (ax - tw / 2, ay + _LABEL_GAP)]
        for step in range(1, 9):                     # then spiral outward
            candidates.append((ax + _LABEL_GAP + step * 18, ay - th / 2 + step * 14))
        chosen = None
        for i, (lx, ly) in enumerate(candidates):
            lx = min(max(lx, 0.0), w - tw)
            ly = min(max(ly, 0.0), h - th)
            r = _rect(lx, ly, tw, th)
            if not any(_overlaps(r, p) for p in placed):
                chosen, displaced = (lx, ly), i >= 4
                break
        if chosen is None:
            continue                                  # no room: drop, never overlap
        lx, ly = chosen
        placed.append(_rect(lx, ly, tw, th))
        labels.append(Label(text, lx, ly, colour, size, priority_of(it)))
        if displaced:
            leaders.append(Leader(ax, ay, lx, ly + th / 2, colour))
    return labels, leaders
