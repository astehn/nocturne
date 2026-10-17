"""Which night a sub belongs to (spec 2026-09-27 §3; §9.1, 2026-09-28).

A night runs from noon to noon, local time, and is named after its evening:
a session that goes past midnight stays one night. His Sh2-108 folder is two
nights, the 21st and the 26th→27th, not the three calendar days it touches.

"Local" is this computer's time zone, the one the Time column already shows
(capture_time.time_label): a chip saying "26 Sep" over rows reading "27 · 00:40"
is right only if both use one zone. DATE-OBS is UTC and converts exactly; the
Seestar's file-name stamp is its own local time, read in this computer's zone
(capture_time.from_filename). Captured abroad and processed at home, both are
off by the zone difference, and a noon boundary has twelve hours of slack
either side of a night's middle before that splits a night. Daylight saving
cannot split one: the clocks change at 02:00-03:00, ten hours from the
boundary, and noon is resolved per date with that date's own offset.

A frame that says where it was taken (SITELONG, which every Seestar sub
carries) turns over at the SITE's solar noon instead, and is named after the
site's evening (2026-10-17). Twelve hours of slack is not enough for a remote
site: a Texas session processed in Europe turns over at 05:00 Texas time,
inside the session, and three nights became four chips judged "mixed". Solar
rather than civil time because the header has no zone, and noon only needs to
be far from the dark. For the owner's own capture folders it changes no
frame's night (tests/fixtures/night_headers.json). The Time column is still
this computer's zone, so for a remote site a chip can read "12 Oct" over
rows reading "13 · 04:30" — a known gap, far smaller than a split night.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .capture_time import site_longitude, to_local

# A night turns over at this local hour — mid-day, as far from any
# observing as a clock gets.
NIGHT_TURNS_AT = 12
# The chip of the frames that carry no capture time at all: there is no
# honest night to put them in, so they are a group of their own.
NO_DATE_LABEL = "No date"


def night_of(dt: datetime | None, site_long=None) -> date | None:
    """The date of the evening a capture time belongs to; None for no time.
    With a usable `site_long`, the evening at the site, by its solar time."""
    if dt is None:
        return None
    lon = site_longitude(site_long)
    if lon is None:
        return (to_local(dt) - timedelta(hours=NIGHT_TURNS_AT)).date()
    solar = dt.astimezone(timezone.utc) + timedelta(hours=lon / 15.0)
    return (solar - timedelta(hours=NIGHT_TURNS_AT)).date()


def night_key(s) -> date | None:
    """A frame's night, from its `captured` and, when known, its site."""
    return night_of(getattr(s, "captured", None), getattr(s, "site_long", None))


def night_label(key: date | None, with_year: bool = False) -> str:
    """"21 Sep" — or "21 Sep 2025" when the folder spans more than one year."""
    if key is None:
        return NO_DATE_LABEL
    text = f"{key.day} {key:%b}"
    return f"{text} {key.year}" if with_year else text


@dataclass(frozen=True)
class Night:
    key: date | None
    frames: tuple
    label: str


def split_nights(stats) -> list[Night]:
    """`stats` grouped by night: dated nights in date order, the undated group
    last. Each night's frames keep the order they were given in."""
    groups: dict[date | None, list] = {}
    for s in stats:
        groups.setdefault(night_key(s), []).append(s)
    keys = sorted(groups, key=lambda k: (k is None, k or date.min))
    years = {k.year for k in keys if k is not None}
    return [Night(k, tuple(groups[k]), night_label(k, with_year=len(years) > 1))
            for k in keys]
