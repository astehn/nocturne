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
