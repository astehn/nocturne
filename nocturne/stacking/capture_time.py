"""When a sub was taken, for the frame list's Time column.

DATE-OBS is UTC on the Seestar — measured 2026-09-27 on his Sh2-108 subs:
Light_SH2-108_10.0s_LP_20260921-221941.fit carries DATE-OBS
2026-09-21T20:19:21.39, two hours behind the filename, which is local time
(CEST). So the header is read as UTC and the filename as local, and both are
shown in local time: "22:19" is what he remembers, not "20:19".
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone, tzinfo

# The zone "local" means everywhere a capture time is shown or grouped into a
# night. None is this computer's own, which is all the app ever uses. Tests pin
# a zone here: the POSIX way (TZ + time.tzset) does not exist on Windows.
LOCAL_ZONE: tzinfo | None = None


def to_local(dt: datetime) -> datetime:
    """An aware time in the local zone."""
    return dt.astimezone(LOCAL_ZONE)


def attach_local(naive: datetime) -> datetime:
    """A naive wall-clock time read as local. `naive.astimezone(zone)` would
    read it as the COMPUTER's time and convert, hence the replace."""
    if LOCAL_ZONE is None:
        return naive.astimezone()
    return naive.replace(tzinfo=LOCAL_ZONE)

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
    return attach_local(naive)


def site_longitude(value) -> float | None:
    """SITELONG as degrees east in [-180, 180), or None when it cannot be
    trusted. 0 is None too: a sub saved without a location fix would carry
    0, and this computer's zone is the better guess then. A site truly on the
    meridian just keeps the behaviour every frame had before 2026-10-17."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        lon = float(value)
    except ValueError:
        return None
    if not math.isfinite(lon) or not -180.0 <= lon <= 360.0:
        return None
    lon = (lon + 180.0) % 360.0 - 180.0
    return None if lon == 0.0 else lon


def read_capture(path: str) -> tuple[datetime | None, float | None]:
    """(capture time, site longitude) from one header read. The time is
    DATE-OBS, else the file name's stamp, else None; the longitude is
    SITELONG through site_longitude, which decides the night (nights.py).

    A header-only read: 0.24 ms a file on real subs (stacker.capture_span), so
    about 60 ms for a 254-frame folder against minutes of grading. Read here
    rather than from load_fits' metadata, whose "date" falls back to the DATE
    card — the file's WRITE time, not when the light arrived.
    """
    from astropy.io import fits
    try:
        header = fits.getheader(path, 0)
        found = from_date_obs(header.get("DATE-OBS"))
        site = site_longitude(header.get("SITELONG"))
    except Exception:          # noqa: BLE001 — a bad card must not lose the frame
        found, site = None, None
    if found is None:
        # The name stamp is the Seestar's clock time at the site, read here in
        # this computer's zone; the site's offset on top would shift it twice.
        return from_filename(path), None
    return found, site


def read_capture_time(path: str) -> datetime | None:
    """DATE-OBS from the header, else the file name's stamp, else None."""
    return read_capture(path)[0]


def time_label(dt: datetime | None) -> str:
    """"21 · 22:30" — day of the month and local time, as the mockup draws it."""
    if dt is None:
        return "—"
    local = to_local(dt)
    return f"{local.day} · {local:%H:%M}"


def full_label(dt: datetime | None) -> str:
    """"21 Sep 2026 22:30:09" for the preview header and tooltip."""
    if dt is None:
        return ""
    local = to_local(dt)
    return f"{local.day} {local:%b %Y %H:%M:%S}"
