"""Adds the nebula catalogues OpenNGC does not carry, from VizieR.

OpenNGC is NGC/IC only. Real annotated astrophotographs — and the references
this feature was designed against — are dense with Sharpless HII regions, Lynds
dark nebulae, Barnard dark nebulae and van den Bergh reflection nebulae. Without
them a wide Cygnus field shows about five objects instead of dozens.

Developer tool, NOT shipped. Appends to the bundled catalogue, skipping any
designation already present, so it is safe to re-run.

    .venv/bin/python scripts/fetch_extra_catalogs.py [--dry-run]

Sources (all via VizieR's ASU-TSV endpoint, using its computed _RAJ2000/_DEJ2000
so every catalogue lands in J2000 regardless of its native epoch):
  VII/20    Sharpless HII regions            -> type HII
  VII/7A    Lynds Dark Nebulae               -> type DrkN
  VII/220A  Barnard Dark Objects             -> type DrkN
  VII/21    van den Bergh reflection nebulae -> type RfN
"""
from __future__ import annotations

import csv
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "nocturne" / "data" / "openngc.csv"
BASE = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"

# (VizieR source, id column, diameter column, diameter unit -> arcmin, name prefix, type)
SOURCES = [
    ("VII/20/catalog", "Sh2", "Diam", 1.0, "Sh2-", "HII"),
    ("VII/7A/ldn", "LDN", "Area", None, "LDN", "DrkN"),
    ("VII/220A/barnard", "Barn", "Diam", 1.0, "B", "DrkN"),
    ("VII/21/catalog", "VdB", None, None, "vdB", "RfN"),
]


def fetch(source: str, cols: list[str]) -> list[dict]:
    q = {"-source": source, "-out": ",".join(cols), "-out.max": "unlimited"}
    url = f"{BASE}?{urllib.parse.urlencode(q, safe=',/_')}"
    with urllib.request.urlopen(url, timeout=120) as r:
        text = r.read().decode("utf-8", "replace")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 3:
        return []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[3:]:                       # skip header, units, separator
        parts = ln.split("\t")
        if len(parts) != len(header):
            continue
        rows.append(dict(zip(header, (p.strip() for p in parts))))
    return rows


def _same_object(ra, dec, major, placed, frac=0.30, size_ratio=3.0) -> bool:
    """True if an already-catalogued object is plainly the same nebula."""
    if major <= 0:
        return False
    for pra, pdec, pmaj in placed:
        if pmaj <= 0:
            continue
        bigger = max(major, pmaj)
        if not (1.0 / size_ratio <= major / pmaj <= size_ratio):
            continue
        d = ((ra - pra) * math.cos(math.radians(dec))) ** 2 + (dec - pdec) ** 2
        if d ** 0.5 <= frac * (bigger / 2.0) / 60.0:
            return True
    return False


def main(dry: bool) -> None:
    with open(OUT, newline="") as f:
        all_rows = list(csv.DictReader(f))
    fields = list(all_rows[0].keys())
    # "Sh2" (no hyphen) is a LEGACY prefix from an earlier run that stored
    # Sharpless names unhyphenated — _pretty_name rendered those as the
    # non-existent "Sh 2117"/"Sh 21". Purge them too or they survive and then
    # block the correctly-named rows as positional duplicates of themselves.
    prefixes = tuple(s[4] for s in SOURCES) + ("Sh2",)
    # Drop anything this script added before, so a re-run replaces rather than
    # duplicates. OpenNGC designations never start with these prefixes.
    existing = [r for r in all_rows if not r["name"].startswith(prefixes)]
    print(f"kept {len(existing)} base rows (dropped {len(all_rows) - len(existing)} previously added)")
    have = {r["name"] for r in existing}
    placed = [(float(r["ra_deg"]), float(r["dec_deg"]),
               float(r["major_arcmin"] or 0.0)) for r in existing]
    added: list[dict] = []
    dup_pos = 0

    for source, id_col, diam_col, diam_scale, prefix, otype in SOURCES:
        cols = ["_RAJ2000", "_DEJ2000", id_col] + ([diam_col] if diam_col else [])
        try:
            rows = fetch(source, cols)
        except Exception as exc:                       # noqa: BLE001 - report, don't die
            print(f"  {prefix:4} FAILED: {exc}")
            continue
        n = 0
        for r in rows:
            ident, ra, dec = r.get(id_col, ""), r.get("_RAJ2000", ""), r.get("_DEJ2000", "")
            if not (ident and ra and dec):
                continue
            name = f"{prefix}{ident.strip()}"
            if name in have:
                continue
            try:
                _ra, _dec = float(ra), float(dec)
            except ValueError:
                continue
            _maj = 0.0
            if diam_col and diam_scale:
                try:
                    _maj = float(r.get(diam_col) or 0) * diam_scale
                except ValueError:
                    _maj = 0.0
            # Same object under another catalogue's designation: centres within
            # 30% of the larger radius and comparable in size. Sh2-117 sits 0.16
            # deg from NGC 7000 and is the same nebula.
            if _same_object(_ra, _dec, _maj, placed):
                dup_pos += 1
                continue
            try:
                ra_deg, dec_deg = float(ra), float(dec)
            except ValueError:
                continue
            major = ""
            if diam_col and diam_scale:
                try:
                    major = f"{float(r.get(diam_col) or 0) * diam_scale:.2f}"
                except ValueError:
                    major = ""
            have.add(name)
            placed.append((_ra, _dec, _maj))
            added.append({f: "" for f in fields} | {
                "name": name, "common": "", "ra_deg": f"{ra_deg:.6f}",
                "dec_deg": f"{dec_deg:.6f}", "major_arcmin": major or "0.00",
                "type": otype, "minor_arcmin": "", "pos_angle": "", "messier": "",
            })
            n += 1
        print(f"  {prefix:4} {source:18} +{n}")

    print(f"total new: {len(added)}  ({dup_pos} skipped as duplicates of catalogued objects)")
    if dry:
        print("dry run — nothing written")
        return
    with open(OUT, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(existing + added)
    print(f"wrote {len(existing) + len(added)} rows to {OUT}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
