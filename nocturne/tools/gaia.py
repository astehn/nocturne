"""Online Gaia DR3 cone-search for photometric colour calibration, via CDS/VizieR
(catalogue I/355/gaiadr3). VizieR is fast and consistent for cone searches (a few
seconds even in the dense Milky Way), unlike ESA's TAP-sync endpoint which swings
from seconds to timeouts under load. Stdlib only, no new dependency; the fetcher
is injectable so tests never hit the network."""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

_VIZIER = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"


class GaiaError(Exception):
    pass


@dataclass
class GaiaStar:
    ra_deg: float
    dec_deg: float
    bp_rp: float
    g_mag: float


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Nocturne/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def query_field(ra_deg: float, dec_deg: float, radius_deg: float, *,
                mag_min: float = 7.0, mag_max: float = 15.0, fetch=None) -> list[GaiaStar]:
    """Gaia DR3 stars within `radius_deg` of (ra,dec) that have a BP-RP colour and a
    sane G magnitude. Raises GaiaError on any network/parse failure or empty result."""
    fetch = fetch or _default_fetch
    query = (
        "-source=I/355/gaiadr3"
        f"&-c={quote(f'{ra_deg:.6f} {dec_deg:+.6f}')}"       # 'RA +DEC' (space, signed dec)
        f"&-c.rd={radius_deg:.4f}"
        f"&-out={quote('RA_ICRS,DE_ICRS,Gmag,BP-RP', safe=',')}"
        "&-out.max=3000"
        f"&Gmag={mag_min:g}..{mag_max:g}"
    )
    url = _VIZIER + "?" + query
    try:
        text = fetch(url)
    except Exception as exc:                      # noqa: BLE001 — any failure -> fallback
        raise GaiaError(f"Gaia query failed: {exc}") from exc
    out = []
    for line in text.splitlines():
        # VizieR TSV: '#' comments, then header/units/separator rows, then tab-separated
        # data. Data rows are exactly those whose four fields parse as floats — so the
        # header ('RA_ICRS'…), units ('deg'…), separator ('---'…) and blank-BP-RP rows
        # all fall out naturally.
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            ra, dec = float(parts[0]), float(parts[1])
            g, bp_rp = float(parts[2]), float(parts[3])
        except ValueError:
            continue
        out.append(GaiaStar(ra, dec, bp_rp, g))
    if not out:
        raise GaiaError("Gaia returned no usable stars")
    return out
