"""Online Gaia DR3 cone-search for photometric colour calibration, via CDS/VizieR
(catalogue I/355/gaiadr3), chosen over ESA's TAP-sync endpoint which swings from
seconds to timeouts under load. Stdlib only, no new dependency; the fetcher and
the reachability probe are both injectable so tests never touch the network.

**This module used to claim VizieR answers "in a few seconds even in the dense
Milky Way". Measured 2026-08-17, it does not:** a 1.2 deg cone sorted by distance
took 17.7 s on M 31 and failed outright at 46 s on M 16. A typical successful
call is 12-18 s. `-sort=_r` is the dominant cost — dropping it took the M 16 case
from a timeout to 18.65 s — but it is what makes the row cap keep frame-covering
stars rather than an edge cluster, so it cannot simply go. Making the query
cheaper is real work with real consequences for which stars SPCC calibrates
against; it is written up in TODO.md rather than guessed at here."""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

_VIZIER = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"


class GaiaError(Exception):
    """Base for every way the catalogue lookup can fail.

    The three subclasses exist because they are three different problems with
    three different answers, and reporting them all as "couldn't reach Gaia"
    sent users looking at their network for faults that were not there.
    """


class GaiaUnreachable(GaiaError):
    """The request itself failed — DNS, refused, timed out."""


class GaiaNoStars(GaiaError):
    """A valid catalogue answer that contained no usable stars. Gaia WAS
    reached; the field simply has nothing in the magnitude range with a colour."""


class GaiaBadResponse(GaiaError):
    """Answered, but with something that is not catalogue data — a throttle
    notice, an error page, a service message. Reproduced against the live
    service on 2026-08-17: under load VizieR returns quickly with no data rows,
    and this used to be indistinguishable from being unreachable."""


@dataclass
class GaiaStar:
    ra_deg: float
    dec_deg: float
    bp_rp: float
    g_mag: float


# Measured against the live service 2026-08-17, a 1.2 deg cone sorted by
# distance: M 31 (sparse) 17.7 s, M 16 (dense Milky Way) failed at 46 s. A
# typical successful call is 12-18 s. The module docstring's claim of "a few
# seconds" no longer holds, so this stays generous on purpose — a shorter limit
# would turn slow-but-working calls into failures, which is the opposite of what
# is wanted. See TODO.md for making the QUERY cheaper, which is the real fix.
_TIMEOUT_S = 60

# A HEAD to the service root, purely to answer "is it there at all". Measured
# 2026-08-17: 0.48 s when up, instant on a DNS failure, and its own 5 s limit
# when the route is black-holed — against the 60 s a doomed query used to take.
# Deliberately through urllib rather than a raw socket, so proxies are honoured
# by the same stack the real request uses.
_PROBE_TIMEOUT_S = 5
_SERVICE_ROOT = "https://vizier.cds.unistra.fr/"


def _default_probe() -> None:
    """Raise if the service cannot be reached. Says nothing about whether the
    QUERY will succeed or be quick — only that something is answering."""
    req = urllib.request.Request(_SERVICE_ROOT, method="HEAD",
                                 headers={"User-Agent": "Nocturne/1.0"})
    urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_S).close()

# A real VizieR answer always carries this in its comment block. Its absence
# means whatever came back is not catalogue data.
_VIZIER_MARKER = "VizieR"


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Nocturne/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", errors="replace")


def query_field(ra_deg: float, dec_deg: float, radius_deg: float, *,
                mag_min: float = 7.0, mag_max: float = 15.0,
                fetch=None, probe=None) -> list[GaiaStar]:
    """Gaia DR3 stars within `radius_deg` of (ra,dec) that have a BP-RP colour and a
    sane G magnitude. Raises GaiaError on any network/parse failure or empty result."""
    # Reachability and slowness are different questions. The query itself takes
    # 12-18 s on a good day, so its timeout must stay generous — but there is no
    # reason to spend that discovering the service is simply not there.
    # A caller supplying its own fetch is not going near the network, so a probe
    # would be meaningless: only probe the real path, or when asked explicitly.
    if probe is None and fetch is None:
        probe = _default_probe
    if probe is not None:
        try:
            probe()
        except Exception as exc:                  # noqa: BLE001 — any failure is "not there"
            raise GaiaUnreachable(f"{type(exc).__name__}: {exc}") from exc
    fetch = fetch or _default_fetch
    query = (
        "-source=I/355/gaiadr3"
        f"&-c={quote(f'{ra_deg:.6f} {dec_deg:+.6f}')}"       # 'RA +DEC' (space, signed dec)
        f"&-c.rd={radius_deg:.4f}"
        "&-sort=_r"                                          # nearest-first, so the out.max cap
        f"&-out={quote('RA_ICRS,DE_ICRS,Gmag,BP-RP', safe=',')}"  # keeps the frame-covering stars,
        "&-out.max=3000"                                     # not an edge cluster in a dense field
        f"&Gmag={mag_min:g}..{mag_max:g}"
    )
    url = _VIZIER + "?" + query
    try:
        text = fetch(url)
    except Exception as exc:                      # noqa: BLE001 — any failure -> fallback
        raise GaiaUnreachable(f"{type(exc).__name__}: {exc}") from exc
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
        if _VIZIER_MARKER not in text:
            # Quote it. Without the body there is nothing to diagnose from, and
            # this is the case that masqueraded as a network failure.
            snippet = " ".join(text.split())[:200] or "(empty response)"
            raise GaiaBadResponse(f"not catalogue data: {snippet}")
        raise GaiaNoStars(
            f"no stars between G {mag_min:g} and {mag_max:g} with a BP-RP colour "
            f"within {radius_deg:.2f} deg")
    return out
