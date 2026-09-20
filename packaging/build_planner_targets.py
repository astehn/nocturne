"""Generate site/planner-targets.json from the OpenNGC data the app ships.

The selection rule is an ARGUMENT, not a constant, and the rule that produced a
file is recorded inside it. Widening the catalogue (design doc 13.2) is then a
regenerate rather than an edit, and the page can always state truthfully what it
contains.

The rule: a common name or a Messier number, and a recorded major axis of at
least `min_arcmin`. The name requirement is the whole design -- it buys curation
for free, because nothing without a name can reach a recommendation.

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
OUT = ROOT / "site" / "planner-targets.json"
MIN_ARCMIN = 5.0
BUDGET_BYTES = 40_000


def read_openngc(path: pathlib.Path = OPENNGC) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_name(row: dict) -> str:
    """What a person calls it. Messier numbers beat catalogue designations."""
    if row.get("messier"):
        return f"M {row['messier'].strip()}"
    return (row.get("common") or "").strip()


def select_targets(rows: list[dict], min_arcmin: float = MIN_ARCMIN) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if not (row.get("common") or row.get("messier")):
            continue
        size = _f(row.get("major_arcmin", ""))
        if size is None or size < min_arcmin:
            continue
        ra, dec = _f(row.get("ra_deg", "")), _f(row.get("dec_deg", ""))
        if ra is None or dec is None:
            continue
        out.append({
            "id": row["name"].strip(),
            "name": _display_name(row),
            "common": (row.get("common") or "").strip(),
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
            "source": "OpenNGC, as shipped in nocturne/data/openngc.csv",
        },
        "targets": targets,
    }


def build(min_arcmin: float = MIN_ARCMIN) -> dict:
    data = payload(select_targets(read_openngc(), min_arcmin), min_arcmin)
    blob = json.dumps(data, separators=(",", ":"))
    if len(blob) > BUDGET_BYTES:
        raise SystemExit(f"planner-targets.json is {len(blob)} bytes, over the "
                         f"{BUDGET_BYTES} budget -- widen deliberately, not by accident")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blob, encoding="utf-8")
    return data


if __name__ == "__main__":
    d = build()
    print(f"wrote {OUT} -- {len(d['targets'])} targets, {OUT.stat().st_size} bytes")
    sys.exit(0)
