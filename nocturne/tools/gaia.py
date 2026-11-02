"""Online Gaia DR3 cone-search for photometric colour calibration: our own copy at
gaia.nocturneastro.com first (see `_MIRROR`), then CDS/VizieR (catalogue
I/355/gaiadr3), chosen over ESA's TAP-sync endpoint which swings from
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

import http.client
import ssl
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

_VIZIER = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"

# Our own copy of the subset SPCC uses, asked first (2026-11-01). Andreas: "More
# often than not Gaia does not work when i try it" -- the night this was
# decided, all of CDS Strasbourg was unreachable. Same path, same parameters,
# same TSV as VizieR, so only the host differs and one parser serves both.
_MIRROR = "https://gaia.nocturneastro.com/viz-bin/asu-tsv"
MIRROR_LABEL = "nocturneastro.com"
VIZIER_LABEL = "VizieR"


class GaiaError(Exception):
    """Base for every way the catalogue lookup can fail.

    The three subclasses exist because they are three different problems with
    three different answers, and reporting them all as "couldn't reach Gaia"
    sent users looking at their network for faults that were not there.
    """


class GaiaUnreachable(GaiaError):
    """The request itself failed — DNS, refused, timed out."""


class GaiaTlsError(GaiaUnreachable):
    """The connection was refused at the TLS layer — a certificate problem on
    THIS computer, not a network one.

    A subclass of GaiaUnreachable so any existing handler keeps working; the
    point is only that a caller which cares can say something accurate.

    Worth its own class because of what it cost. Until v0.21.0 the built app
    shipped no CA certificates and resolved them against the build machine's
    Homebrew path, so on every other Mac this failed — and was reported as
    "Couldn't reach Gaia", which named a plausible cause instead of the real
    one. It went into the backlog as a slow-catalogue problem and sat there for
    weeks while Andreas simply learned to expect SPCC not to work on that
    computer. Telling a user to check their network for a fault that is in the
    application is worse than saying nothing.
    """


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


class GaiaStars(list):
    """The stars, plus which source answered and why the mirror did not.

    A list subclass so every caller and fake written against a plain list keeps
    working; the colour step reads the two attributes with getattr."""
    source: str = VIZIER_LABEL
    mirror_failure: str | None = None


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


def _unreachable_kind(exc: BaseException) -> type:
    """GaiaTlsError if this failure was TLS, GaiaUnreachable otherwise.

    urllib wraps the real cause: an SSLCertVerificationError arrives as a
    URLError with the SSL error in `.reason`, so the type alone is not enough.
    """
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLError):
            return GaiaTlsError
        exc = getattr(exc, "reason", None) or exc.__cause__
    return GaiaUnreachable


def _default_probe() -> None:
    """Raise if the service cannot be reached. Says nothing about whether the
    QUERY will succeed or be quick — only that something is answering."""
    req = urllib.request.Request(_SERVICE_ROOT, method="HEAD",
                                 headers={"User-Agent": "Nocturne/1.0"})
    urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT_S).close()

# A real VizieR answer always carries this in its comment block. Its absence
# means whatever came back is not catalogue data.
_VIZIER_MARKER = "VizieR"

# The mirror's first comment line carries this instead. Each source is checked
# against its own marker, so an error page that mentions VizieR does not pass
# for an answer from our host.
_MIRROR_MARKER = "Nocturne Gaia mirror"

# The mirror reads a local file and should answer in well under a second, so a
# dead or slow one must not eat into VizieR's chance. urllib's timeout is per
# socket operation, so a server sending a byte every few seconds would never
# trip it (the final review held a read open past 15 s with a 2 s limit): the
# total is a separate deadline on the read. Measured live 2026-11-02: 0.14 s on
# M 16, 0.99 s on the densest 1.2 deg field in the sky. DNS is outside both.
_MIRROR_TIMEOUT_S = 3
_MIRROR_TOTAL_S = 10


def _fetch(url: str, timeout: float, total: float | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Nocturne/1.0"})
    deadline = None if total is None else time.monotonic() + total
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if deadline is None:
            return resp.read().decode("utf-8", errors="replace")
        chunks = []
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"no complete answer within {total:g} s")
            block = resp.read1(65536)
            if not block:
                break
            chunks.append(block)
        if resp.length:   # read1 does not, unlike read(), refuse a short body
            raise http.client.IncompleteRead(b"".join(chunks), resp.length)
        return b"".join(chunks).decode("utf-8", errors="replace")


def _default_fetch(url: str) -> str:
    return _fetch(url, _TIMEOUT_S)


def _default_mirror_fetch(url: str) -> str:
    return _fetch(url, _MIRROR_TIMEOUT_S, _MIRROR_TOTAL_S)


def query_field(ra_deg: float, dec_deg: float, radius_deg: float, *,
                mag_min: float = 7.0, mag_max: float = 15.0,
                fetch=None, probe=None, mirror_fetch=None) -> GaiaStars:
    """Gaia DR3 stars within `radius_deg` of (ra,dec) that have a BP-RP colour and a
    sane G magnitude: from our mirror if it answers, else from VizieR. Raises
    GaiaError when VizieR fails too.

    The mirror is asked on the real path (nothing injected) or when a
    `mirror_fetch` is given. A caller that injects only `fetch` is a test of the
    VizieR path and must not reach the network for the mirror."""
    query = (
        "-source=I/355/gaiadr3"
        f"&-c={quote(f'{ra_deg:.6f} {dec_deg:+.6f}')}"       # 'RA +DEC' (space, signed dec)
        f"&-c.rd={radius_deg:.4f}"
        "&-sort=_r"                                          # nearest-first, so the out.max cap
        f"&-out={quote('RA_ICRS,DE_ICRS,Gmag,BP-RP', safe=',')}"  # keeps the frame-covering stars,
        "&-out.max=3000"                                     # not an edge cluster in a dense field
        f"&Gmag={mag_min:g}..{mag_max:g}"
    )
    if mirror_fetch is None and fetch is None:
        mirror_fetch = _default_mirror_fetch
    mirror_failure = None
    if mirror_fetch is not None:
        # Every failure falls through, "no stars" included: no field SPCC asks
        # about is empty to G 15, so an empty answer means a broken mirror.
        try:
            text = mirror_fetch(_MIRROR + "?" + query)
            # Our server always opens with its marker, so anything else on that
            # path is not our answer, rows or no rows.
            if not text.startswith("#" + _MIRROR_MARKER):
                snippet = " ".join(text.split())[:200] or "(empty response)"
                raise GaiaBadResponse(f"not catalogue data: {snippet}")
            out = _parse_rows(text, _MIRROR_MARKER, mag_min, mag_max, radius_deg)
            out.source = MIRROR_LABEL
            return out
        except Exception as exc:                  # noqa: BLE001 — any failure -> VizieR
            mirror_failure = f"{type(exc).__name__}: {exc}"
            mirror_kind = _unreachable_kind(exc)
    try:
        out = _query_vizier(query, mag_min, mag_max, radius_deg, fetch, probe)
    except GaiaError as exc:
        if mirror_failure is None:
            raise
        # A certificate fault on this computer shows on the mirror even while
        # CDS is simply down, the case the mirror exists for. Name it, rather
        # than "Couldn't reach Gaia" (the v0.21.0 misreport).
        kind = type(exc)
        if mirror_kind is GaiaTlsError and isinstance(exc, GaiaUnreachable):
            kind = GaiaTlsError
        raise kind(f"{MIRROR_LABEL}: {mirror_failure}; "
                   f"{VIZIER_LABEL}: {exc}") from exc
    out.mirror_failure = mirror_failure
    return out


def _query_vizier(query: str, mag_min: float, mag_max: float, radius_deg: float,
                  fetch, probe) -> GaiaStars:
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
            raise _unreachable_kind(exc)(f"{type(exc).__name__}: {exc}") from exc
    fetch = fetch or _default_fetch
    try:
        text = fetch(_VIZIER + "?" + query)
    except Exception as exc:                      # noqa: BLE001 — any failure -> fallback
        raise _unreachable_kind(exc)(f"{type(exc).__name__}: {exc}") from exc
    out = _parse_rows(text, _VIZIER_MARKER, mag_min, mag_max, radius_deg)
    out.source = VIZIER_LABEL
    return out


def _parse_rows(text: str, marker: str, mag_min: float, mag_max: float,
                radius_deg: float) -> GaiaStars:
    out = GaiaStars()
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
        if marker not in text:
            # Quote it. Without the body there is nothing to diagnose from, and
            # this is the case that masqueraded as a network failure.
            snippet = " ".join(text.split())[:200] or "(empty response)"
            raise GaiaBadResponse(f"not catalogue data: {snippet}")
        raise GaiaNoStars(
            f"no stars between G {mag_min:g} and {mag_max:g} with a BP-RP colour "
            f"within {radius_deg:.2f} deg")
    return out
