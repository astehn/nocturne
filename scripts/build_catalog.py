"""Regenerates nocturne/data/openngc.csv from OpenNGC.

Developer tool — NOT shipped in the app. OpenNGC (c) Mattia Verga, CC BY-SA 4.0,
already credited in NOTICE; the derivative keeps those terms.

    .venv/bin/python scripts/build_catalog.py path/to/NGC.csv

Source columns used: Name, Type, RA, Dec, MajAx, MinAx, PosAng, M, Common names.

`name` is always the OpenNGC designation (e.g. "NGC0224") — never renamed to a
Messier alias. Messier membership is carried separately in the `messier`
column (e.g. "31"), so target metadata / provenance reports keep the stable
catalogue identity while callers that want "M 31" can compose it themselves.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "nocturne" / "data" / "openngc.csv"
FIELDS = ["name", "common", "ra_deg", "dec_deg", "major_arcmin",
          "type", "minor_arcmin", "pos_angle", "messier"]


def _hms_to_deg(s: str) -> float:
    h, m, sec = (float(p) for p in s.split(":"))
    return (h + m / 60 + sec / 3600) * 15.0


def _dms_to_deg(s: str) -> float:
    sign = -1.0 if s.strip().startswith("-") else 1.0
    d, m, sec = (float(p) for p in s.strip().lstrip("+-").split(":"))
    return sign * (d + m / 60 + sec / 3600)


def main(src: str) -> None:
    rows = []
    with open(src, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            name, ra, dec = r.get("Name", ""), r.get("RA", ""), r.get("Dec", "")
            if not (name and ra and dec) or r.get("Type") in ("Dup", "NonEx"):
                continue
            try:
                ra_deg, dec_deg = _hms_to_deg(ra), _dms_to_deg(dec)
            except ValueError:
                continue
            messier = (r.get("M") or "").strip()
            rows.append({
                "name": name,
                "common": (r.get("Common names") or "").split(",")[0].strip(),
                "ra_deg": f"{ra_deg:.6f}",
                "dec_deg": f"{dec_deg:.6f}",
                "major_arcmin": r.get("MajAx") or "",
                "type": (r.get("Type") or "").strip(),
                "minor_arcmin": r.get("MinAx") or "",
                "pos_angle": r.get("PosAng") or "",
                "messier": str(int(messier)) if messier.isdigit() else "",
            })
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
