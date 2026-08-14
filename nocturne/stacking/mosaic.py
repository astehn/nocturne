"""Turning many pointings into one canvas.

`run_stack` registers every frame to one reference and integrates onto a canvas
the shape of that frame, so a panel that does not overlap the reference has no
transform to find. This module groups the subs by pointing, stacks each group
with the ordinary stacker, and places the resulting masters by their plate
solutions — geometry between panels comes from astrometry rather than star
matching, because a similarity transform cannot represent the mapping between
two gnomonic projections, and the error it leaves grows with panel separation
(measured on real M 31 panels: 0.52 px against a homography's 0.16 px).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Panel:
    centre_ra: float
    centre_dec: float
    paths: tuple[str, ...]


def _separation_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Small-angle sky separation. Exact enough below a few degrees, which is
    every mosaic a Seestar can shoot, and it keeps the maths readable."""
    dec_mid = math.radians((a[1] + b[1]) / 2.0)
    dra = (a[0] - b[0]) * math.cos(dec_mid)
    return math.hypot(dra, a[1] - b[1])


def discover_panels(pointings: dict[str, tuple[float, float]],
                    radius_deg: float) -> list[Panel]:
    """Group frames into panels by SINGLE LINKAGE — a frame joins a panel if it
    is within `radius_deg` of ANY member, not of a moving centroid.

    Order independence is the point. A greedy centroid shifts as it absorbs
    members, so the same frames cluster differently depending on the order they
    arrive in; two spikes on one 392-sub set produced 22 panels and 29 that way.

    Header RA/DEC is the mount's COMMANDED pointing, which is useless for dither
    (99% of consecutive frames report no movement) and exactly right here: the
    mount's intent is what defines a panel.
    """
    paths = sorted(pointings)
    parent = {p: p for p in paths}

    def find(p: str) -> str:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if _separation_deg(pointings[a], pointings[b]) <= radius_deg:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

    groups: dict[str, list[str]] = {}
    for p in paths:
        groups.setdefault(find(p), []).append(p)

    panels = []
    for members in groups.values():
        ras = [pointings[m][0] for m in members]
        decs = [pointings[m][1] for m in members]
        panels.append(Panel(sum(ras) / len(ras), sum(decs) / len(decs),
                            tuple(sorted(members))))
    # deterministic output order: north first, then east
    return sorted(panels, key=lambda p: (-p.centre_dec, p.centre_ra))
