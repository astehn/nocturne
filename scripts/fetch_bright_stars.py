"""Adds Bayer/Flamsteed star designations from the Yale Bright Star Catalogue.

The bundled named_stars.csv holds 371 IAU proper names (Vega, Deneb, ...). In a
2-3 degree field there are usually none, so "Named stars" appeared to do
nothing. Annotated references label Bayer/Flamsteed designations instead —
"nu Cyg", "21 Sgr", "13 mu Sgr" — which come from the BSC (VizieR V/50).

Existing proper names are kept and win: a BSC star within MATCH_DEG of one
already listed is skipped, so Deneb never also appears as "alpha Cyg".

Developer tool, NOT shipped. Safe to re-run.

    .venv/bin/python scripts/fetch_bright_stars.py [--dry-run] [--maglimit 6.5]
"""
from __future__ import annotations

import csv
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "nocturne" / "data" / "named_stars.csv"
BASE = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
MATCH_DEG = 0.02          # a BSC row this close to an existing name is the same star

_GREEK = {
    "Alp": "α", "Bet": "β", "Gam": "γ", "Del": "δ", "Eps": "ε", "Zet": "ζ",
    "Eta": "η", "The": "θ", "Iot": "ι", "Kap": "κ", "Lam": "λ", "Mu": "μ",
    "Nu": "ν", "Xi": "ξ", "Omi": "ο", "Pi": "π", "Rho": "ρ", "Sig": "σ",
    "Tau": "τ", "Ups": "υ", "Phi": "φ", "Chi": "χ", "Psi": "ψ", "Ome": "ω",
}


def pretty(packed: str) -> str:
    """'21Alp And' -> 'α And';  '88Gam Peg' -> 'γ Peg';  '21 Sgr' -> '21 Sgr'.

    A Bayer letter is more recognisable than a Flamsteed number, so it wins when
    a star has both; the number is the fallback for stars that lack one."""
    packed = packed.strip()
    if not packed or " " not in packed:
        return ""
    designation, const = packed.rsplit(" ", 1)
    designation = designation.strip()
    digits = "".join(c for c in designation if c.isdigit())
    letters = "".join(c for c in designation if not c.isdigit()).strip()
    greek = _GREEK.get(letters[:3].capitalize()) if letters else None
    if greek:
        return f"{greek} {const}"
    if digits:
        return f"{digits} {const}"
    return ""


def main(dry: bool, maglimit: float) -> None:
    existing = list(csv.DictReader(open(OUT, newline="")))
    kept = [(float(r["ra_deg"]), float(r["dec_deg"])) for r in existing]
    q = {"-source": "V/50/catalog", "-out": "Name,Vmag,_RAJ2000,_DEJ2000",
         "-out.max": "unlimited", "Vmag": f"<{maglimit}"}
    url = f"{BASE}?{urllib.parse.urlencode(q, safe=',/_<')}"
    with urllib.request.urlopen(url, timeout=120) as r:
        text = r.read().decode("utf-8", "replace")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    header = lines[0].split("\t")

    added, skipped_dup, unnamed = [], 0, 0
    for ln in lines[3:]:
        parts = ln.split("\t")
        if len(parts) != len(header):
            continue
        row = dict(zip(header, (p.strip() for p in parts)))
        name = pretty(row.get("Name", ""))
        if not name:
            unnamed += 1
            continue
        try:
            ra, dec, mag = (float(row["_RAJ2000"]), float(row["_DEJ2000"]),
                            float(row["Vmag"]))
        except (ValueError, KeyError):
            continue
        if any(abs(ra - a) < MATCH_DEG and abs(dec - b) < MATCH_DEG for a, b in kept):
            skipped_dup += 1
            continue
        kept.append((ra, dec))
        added.append({"name": name, "ra_deg": f"{ra:.5f}",
                      "dec_deg": f"{dec:.5f}", "mag": f"{mag:.2f}"})

    print(f"BSC <= mag {maglimit}: +{len(added)} added, {skipped_dup} already named, "
          f"{unnamed} without a Bayer/Flamsteed designation")
    print(f"catalogue {len(existing)} -> {len(existing) + len(added)}")
    if dry:
        print("dry run — nothing written")
        return
    with open(OUT, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["name", "ra_deg", "dec_deg", "mag"])
        wr.writeheader()
        wr.writerows(existing + added)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    lim = 6.5
    if "--maglimit" in sys.argv:
        lim = float(sys.argv[sys.argv.index("--maglimit") + 1])
    main("--dry-run" in sys.argv, lim)
