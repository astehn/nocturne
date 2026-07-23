"""Online Gaia DR3 cone-search for photometric colour calibration. One HTTPS call
to ESA's Gaia TAP sync endpoint; stdlib only, no new dependency. The fetcher is
injectable so tests never hit the network."""
from __future__ import annotations

import csv
import io
import urllib.parse
import urllib.request
from dataclasses import dataclass

_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"


class GaiaError(Exception):
    pass


@dataclass
class GaiaStar:
    ra_deg: float
    dec_deg: float
    bp_rp: float
    g_mag: float


def _default_fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def query_field(ra_deg: float, dec_deg: float, radius_deg: float, *,
                mag_min: float = 7.0, mag_max: float = 16.0, fetch=None) -> list[GaiaStar]:
    """Gaia DR3 stars within `radius_deg` of (ra,dec) with a BP-RP colour and a
    sane magnitude. Raises GaiaError on any network/parse failure or empty result."""
    fetch = fetch or _default_fetch
    adql = (
        "SELECT TOP 3000 ra, dec, phot_g_mean_mag, bp_rp FROM gaiadr3.gaia_source "
        "WHERE CONTAINS(POINT('ICRS',ra,dec), "
        f"CIRCLE('ICRS', {ra_deg:.6f}, {dec_deg:.6f}, {radius_deg:.6f}))=1 "
        f"AND bp_rp IS NOT NULL AND phot_g_mean_mag BETWEEN {mag_min:g} AND {mag_max:g}"
    )
    url = _TAP + "?" + urllib.parse.urlencode(
        {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql})
    try:
        text = fetch(url)
    except Exception as exc:                      # noqa: BLE001 — any failure -> fallback
        raise GaiaError(f"Gaia query failed: {exc}") from exc
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append(GaiaStar(float(row["ra"]), float(row["dec"]),
                                float(row["bp_rp"]), float(row["phot_g_mean_mag"])))
        except (ValueError, KeyError):
            continue                              # skip rows with missing/blank fields
    if not out:
        raise GaiaError("Gaia returned no usable stars")
    return out
