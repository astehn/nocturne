"""When a sub was taken, for the frame list's Time column.

DATE-OBS is UTC on the Seestar — measured 2026-09-27 on his Sh2-108 subs:
Light_SH2-108_10.0s_LP_20260921-221941.fit carries DATE-OBS
2026-09-21T20:19:21.39, two hours behind the filename, which is local time
(CEST). So the header is read as UTC and the filename as local, and both are
shown in local time: "22:19" is what he remembers, not "20:19".
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

# ..._LP_20260921-223009.fit — the Seestar's local capture stamp, last before
# the extension.
_STAMP = re.compile(r"(\d{8})-(\d{6})$")


def from_date_obs(value) -> datetime | None:
    """A FITS DATE-OBS value as an aware UTC datetime, or None."""
    if not value:
        return None
    text = str(value).strip().rstrip("Z")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)   # FITS: UTC unless TIMESYS says otherwise
    return dt


def from_filename(path: str) -> datetime | None:
    """The Seestar's own stamp in the file name, read as LOCAL time."""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = _STAMP.search(stem)
    if not m:
        return None
    try:
        naive = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return naive.astimezone()      # attach the machine's local zone


def read_capture_time(path: str) -> datetime | None:
    """DATE-OBS from the header, else the file name's stamp, else None.

    A header-only read: 0.24 ms a file on real subs (stacker.capture_span), so
    about 60 ms for a 254-frame folder against minutes of grading. Read here
    rather than from load_fits' metadata, whose "date" falls back to the DATE
    card — the file's WRITE time, not when the light arrived.
    """
    from astropy.io import fits
    try:
        found = from_date_obs(fits.getheader(path, 0).get("DATE-OBS"))
    except Exception:          # noqa: BLE001 — a bad card must not lose the frame
        found = None
    return found or from_filename(path)


def time_label(dt: datetime | None) -> str:
    """"21 · 22:30" — day of the month and local time, as the mockup draws it."""
    if dt is None:
        return "—"
    local = dt.astimezone()
    return f"{local.day} · {local:%H:%M}"


def full_label(dt: datetime | None) -> str:
    """"21 Sep 2026 22:30:09" for the preview header and tooltip."""
    if dt is None:
        return ""
    local = dt.astimezone()
    return f"{local.day} {local:%b %Y %H:%M:%S}"
