"""Generate site/planner-targets.json from the OpenNGC data the app ships.

The selection rule is an ARGUMENT, not a constant, and the rule that produced a
file is recorded inside it. Widening the catalogue (design doc 13.2) is then a
regenerate rather than an edit, and the page can always state truthfully what it
contains.

The rule: a common name or a Messier number, and a recorded major axis of at
least `min_arcmin`. The name requirement is the whole design -- it buys curation
for free, because nothing without a name can reach a recommendation.

A NAME MAY COME FROM EITHER FILE. nocturne/data/common_names.csv is the app's
hand-curated overlay for objects whose catalogues carry none, and this generator
used to ignore it -- so thirteen objects with perfectly good coordinates were
dropped for want of a name that was already written down one directory away.
Two of them were on the wall at the time: NGC 281, and the Sh 2-142 somebody had
submitted a picture of. Neither could be promoted, because the planner had no
target to promote them to.

AND A FEW OBJECTS ARE NOT IN OpenNGC AT ALL. It is NGC and IC only, so M 45 --
Melotte 22, no NGC number -- was never a candidate to begin with. Those live in
packaging/planner_extra_targets.csv, hand-entered and anchored to a nearby
catalogued object so a typo fails a test instead of misplacing an object.

THERE IS NO UPPER SIZE BOUND, and that is deliberate. An earlier draft capped
size at the S30 Pro's 135' short axis, which silently removed M 31, the Veil, the
California Nebula, the Witch Head and the SMC. Size informs how framing is
described; it never decides membership.

    .venv/bin/python packaging/build_planner_targets.py
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPENNGC = ROOT / "nocturne" / "data" / "openngc.csv"
COMMON_NAMES = ROOT / "nocturne" / "data" / "common_names.csv"
EXTRA = ROOT / "packaging" / "planner_extra_targets.csv"
OUT = ROOT / "site" / "planner-targets.json"
# 1 arcminute, not 5. At 5 the floor removed the Ring Nebula (1.27'), the Owl,
# M 78 and the Little Dumbbell -- and for a small scope the compact objects are
# exactly the ones worth planning for. The name requirement is what keeps the
# list curated; size never was doing that job. 158 targets -> 187, +3 kB.
MIN_ARCMIN = 1.0
BUDGET_BYTES = 40_000


def read_openngc(path: pathlib.Path = OPENNGC) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_common_names(path: pathlib.Path = COMMON_NAMES) -> dict[str, str]:
    """The app's hand-curated names, keyed by designation.

    Comment lines carry the reasoning for the rows below them and must be
    skipped; csv.DictReader does not do that on its own.
    """
    out: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    for row in csv.DictReader(lines):
        designation = (row.get("designation") or "").strip()
        common = (row.get("common") or "").strip()
        if designation and common:
            out[designation] = common
    return out


def read_extra(path: pathlib.Path = EXTRA) -> list[dict]:
    """Objects OpenNGC does not carry, hand-entered. See that file's header."""
    with open(path, newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines))


def _display_name(row: dict, overlay: dict[str, str] | None = None) -> str:
    """What a person calls it. Messier numbers beat catalogue designations."""
    if row.get("messier"):
        return f"M {row['messier'].strip()}"
    common = (row.get("common") or "").strip()
    if common:
        return common
    # The overlay is consulted LAST, so a name OpenNGC does carry always wins.
    # These are colloquial names; the catalogue is the authority where it has an
    # opinion at all.
    return (overlay or {}).get(row.get("name", "").strip(), "")


def select_targets(rows: list[dict], min_arcmin: float = MIN_ARCMIN,
                   overlay: dict[str, str] | None = None,
                   extra: list[dict] | None = None) -> list[dict]:
    overlay = read_common_names() if overlay is None else overlay
    out: list[dict] = []
    for row in rows:
        name = _display_name(row, overlay)
        if not name:
            continue
        size = _f(row.get("major_arcmin", ""))
        if size is None or size < min_arcmin:
            continue
        ra, dec = _f(row.get("ra_deg", "")), _f(row.get("dec_deg", ""))
        if ra is None or dec is None:
            continue
        out.append({
            "id": row["name"].strip(),
            "name": name,
            # `common` follows the name the list actually shows, so an overlay
            # name reaches the admin's search box and the tile caption too --
            # otherwise "Pacman Nebula" would be findable by id alone.
            "common": (row.get("common") or "").strip()
                      or overlay.get(row["name"].strip(), ""),
            "ra": round(ra, 4),
            "dec": round(dec, 4),
            "size": round(size, 1),
            "type": (row.get("type") or "").strip(),
        })
    for row in (read_extra() if extra is None else extra):
        size = _f(row.get("major_arcmin", ""))
        ra, dec = _f(row.get("ra_deg", "")), _f(row.get("dec_deg", ""))
        if size is None or ra is None or dec is None or size < min_arcmin:
            continue
        common = (row.get("common") or "").strip()
        out.append({
            "id": row["designation"].strip(),
            "name": common,
            "common": common,
            "ra": round(ra, 4),
            "dec": round(dec, 4),
            "size": round(size, 1),
            "type": (row.get("type") or "").strip(),
        })
    out.sort(key=lambda t: t["id"])
    return out


def payload(targets: list[dict], min_arcmin: float = MIN_ARCMIN) -> dict:
    return {
        "rule": {
            "requires_name": True,
            "min_arcmin": min_arcmin,
            "max_arcmin": None,       # deliberately unbounded -- see the docstring
            "source": "OpenNGC, as shipped in nocturne/data/openngc.csv, "
                      "named also from common_names.csv, plus "
                      "planner_extra_targets.csv for objects OpenNGC omits",
        },
        "targets": targets,
    }


def build(min_arcmin: float = MIN_ARCMIN, out: pathlib.Path | None = None) -> dict:
    """Write the catalogue. `out` exists so a TEST can build without shipping.

    This used to write to site/planner-targets.json unconditionally, and one of
    the tests below calls it -- so running the suite regenerated a deployable
    artifact as a side effect. Widening the catalogue is supposed to be a
    deliberate regenerate (this module's whole premise); a test doing it
    silently meant the file could change under you and be rsynced without
    anyone having decided to. Found 2026-09-24, by a snapshot taken "before" a
    rebuild already containing the rebuild.
    """
    out = OUT if out is None else out
    data = payload(select_targets(read_openngc(), min_arcmin), min_arcmin)
    blob = json.dumps(data, separators=(",", ":"))
    if len(blob) > BUDGET_BYTES:
        raise SystemExit(f"planner-targets.json is {len(blob)} bytes, over the "
                         f"{BUDGET_BYTES} budget -- widen deliberately, not by accident")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob, encoding="utf-8")
    return data


if __name__ == "__main__":
    d = build()
    print(f"wrote {OUT} -- {len(d['targets'])} targets, {OUT.stat().st_size} bytes")
    sys.exit(0)
