"""Refuse to train on an unsound split — checked in seconds, before anything long.

Every split guard in this project compares target NAMES for equality:
`HELD_OUT`, `S30_TRAIN`, `_split_name`, the `SAME_SKY` pairs. That held while one
person maintained one archive with one naming convention. It stopped holding the
day the archive was rebuilt off the Seestar after the 2026-08-25 disk loss, which
named every folder `M 8_sub` where the lists say `M8`. Measured 2026-08-30: all
four held-out targets — the only honest tests this project has — passed straight
into training material, and nothing anywhere would have said so. The model would
have trained, passed its gate, and been judged on sky it had memorised.

Two different problems live here, and they need different answers.

NAMES drift, so identity is normalised rather than compared raw ("M 8_sub", "M8"
and "m8" are one target). That re-arms the guards that already exist.

SKY cannot be recovered from a name at all. `MilkyWay_sub` in this archive is
M 17 shot a second time — 275.61/-16.15 against 275.60/-16.15 — and no list will
ever know that unless somebody notices and writes it down. `SAME_SKY` is exactly
such a hand-maintained list and it has one entry in it. So sky identity is read
from where the telescope was actually pointing.

This runs as a preflight because the tiles a dataset is made of carry names, not
coordinates: enforcing this at load time means changing the dataset format. A
check that costs seconds against the real archive buys the same safety before a
two-hour build, which is the point.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Seestar S30 Pro's long axis is about 1.3 degrees. The SAME_SKY comment in
# data.py calls 0.46 degrees "well inside a single frame", which is the same
# judgement from the other side. 1.0 sits between them: wide enough to catch two
# framings of one object, tight enough not to marry neighbours that merely share
# a constellation. Every separation is printed, so this number can be argued
# with from evidence rather than defended.
DEFAULT_RADIUS_DEG = 1.0

_TRAILING = re.compile(r"[_\s-]*(sub|subs|lp|ircut|mosaic|timelapse)$", re.I)
_NONALNUM = re.compile(r"[^a-z0-9]+")


def canonical(name: str) -> str:
    """One identity for the many ways a target gets written down.

    Strips the suffixes the archive picked up ("_sub") and the filter names that
    ride along ("NGC 281 LP"), then removes spacing and case. Deliberately keeps
    digits distinct, so M8 and M80 stay two targets — over-normalising would
    quietly merge real data, which is the same class of bug pointing the other
    way.
    """
    s = name.strip().lower()
    while True:
        stripped = _TRAILING.sub("", s).strip(" _-")
        if stripped == s:
            break
        s = stripped
    return _NONALNUM.sub("", s)


def held_out_hits(names) -> list:
    """Which of `names` are held-out targets, matched after normalising."""
    from data import HELD_OUT
    held = {canonical(h) for h in HELD_OUT}
    return [n for n in names if canonical(n) in held]


def separation_deg(a: tuple, b: tuple) -> float:
    """Angular separation between two (RA, Dec) in degrees.

    On the sphere, not in raw coordinates: at Dec +57 — where both IC 1396A and
    NGC 281 sit — a degree of RA is about half a degree of sky, so comparing RA
    directly would both invent collisions and miss real ones.
    """
    ra1, dec1 = math.radians(a[0]), math.radians(a[1])
    ra2, dec2 = math.radians(b[0]), math.radians(b[1])
    cos_sep = (math.sin(dec1) * math.sin(dec2)
               + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def sky_clusters(pointings: dict, radius_deg: float = DEFAULT_RADIUS_DEG) -> list:
    """Groups whose pointings fall within `radius_deg` of each other, as sets.

    Transitive on purpose: A near B and B near C puts all three together even if
    A and C are further apart than the radius. Splitting a chain would put
    overlapping sky either side of a split boundary, which is the thing being
    prevented.
    """
    names = sorted(pointings)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if separation_deg(pointings[a], pointings[b]) <= radius_deg:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

    out: dict = {}
    for n in names:
        out.setdefault(find(n), set()).add(n)
    return list(out.values())


@dataclass
class Collision:
    reason: str          # "split" | "unassigned"
    members: list = field(default_factory=list)
    detail: str = ""


def split_collisions(clusters, assignment: dict) -> list:
    """Clusters that break the split, and groups belonging to no split at all.

    An unassigned group is reported rather than ignored: `split_by_target` does
    raise on those, but only once training has started.
    """
    bad = []
    for members in clusters:
        homes = {assignment.get(m) for m in members}
        if None in homes:
            missing = sorted(m for m in members if assignment.get(m) is None)
            bad.append(Collision("unassigned", sorted(members),
                                 f"no split assigned: {', '.join(missing)}"))
            continue
        if len(homes) > 1:
            bad.append(Collision("split", sorted(members),
                                 f"one patch of sky across {sorted(homes)}"))
    return bad


# Mount points that are the NAS. Andreas, 2026-08-30: "I don't want under any
# circumstances that the data on the NAS is changed — use the local data in
# /Volumes/Work/Astro and then copy what you need from there." The NAS is the
# backup of an archive that has already been lost once; nothing here may write
# to it, and the cheapest way to guarantee that is to refuse to point at it at
# all. Read-only intent is not a guarantee — a later flag or a typo is.
_NAS_ROOTS = ("/Volumes/Astro", "/Volumes/Images", "/Volumes/Backup",
              "/Volumes/Download", "/Volumes/usbshare1-2")


def refuse_nas(path: str) -> None:
    real = os.path.realpath(path)
    for nas in _NAS_ROOTS:
        if real == nas or real.startswith(nas + os.sep):
            raise ValueError(
                f"{path} is on the NAS. Training reads and writes the LOCAL "
                f"archive (/Volumes/Work/Astro); copy from the NAS by hand if "
                f"something is missing. The NAS is a backup of data that has "
                f"already been lost once.")


def _pointings_from_archive(root: str) -> dict:
    refuse_nas(root)
    from astropy.io import fits

    from nocturne.training.pairs import discover_frame_groups
    out = {}
    for g in discover_frame_groups(root, sensor=None, min_frames=3,
                                   combine_nights=True):
        h = fits.getheader(g.frames[0].path)
        ra, dec = h.get("RA"), h.get("DEC")
        if ra is None or dec is None:
            continue
        out[g.target_dir] = (float(ra), float(dec), len(g.frames))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archive", default="/Volumes/Work/Astro",
                    help="root of the raw sub archive")
    ap.add_argument("--radius", type=float, default=DEFAULT_RADIUS_DEG,
                    help="degrees within which two pointings are the same sky")
    args = ap.parse_args(argv)

    raw = _pointings_from_archive(args.archive)
    if not raw:
        print(f"no groups with pointings found under {args.archive}")
        return 2
    pointings = {k: (v[0], v[1]) for k, v in raw.items()}
    counts = {k: v[2] for k, v in raw.items()}

    print(f"{len(pointings)} groups under {args.archive}\n")

    held = held_out_hits(pointings)
    print("HELD OUT — never training material:")
    for n in sorted(held):
        print(f"  {n:<26}{counts[n]:>6} frames")
    from data import HELD_OUT
    unmatched = [h for h in HELD_OUT
                 if canonical(h) not in {canonical(n) for n in pointings}]
    if unmatched:
        print(f"  !! named in HELD_OUT but absent from the archive: {unmatched}")
        print("     a guard that matches nothing is a guard that is off.")

    clusters = sky_clusters(pointings, args.radius)
    shared = [c for c in clusters if len(c) > 1]
    print(f"\nSHARED SKY (within {args.radius} deg) — must never be split apart:")
    if not shared:
        print("  none")
    for c in shared:
        names = sorted(c, key=lambda n: -counts[n])
        print(f"  {' + '.join(names)}")
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                print(f"      {a} .. {b}: {separation_deg(pointings[a], pointings[b]):.3f} deg")

    print("\nDEPTH available to training (held-out and shared-sky duplicates removed):")
    usable, seen = [], set()
    for c in sorted(clusters, key=lambda c: -max(counts[m] for m in c)):
        if any(canonical(m) in {canonical(h) for h in held} for m in c):
            continue
        best = max(c, key=lambda m: counts[m])
        if canonical(best) in seen:
            continue
        seen.add(canonical(best))
        usable.append((counts[best], best, sorted(c)))
    for n, best, members in usable:
        extra = f"  (+{len(members) - 1} more of the same sky)" if len(members) > 1 else ""
        print(f"  {best:<26}{n:>6} frames{extra}")
    deep = [n for n, _, _ in usable if n >= 200]
    print(f"\n  {len(usable)} usable groups, {len(deep)} of them 200+ frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
