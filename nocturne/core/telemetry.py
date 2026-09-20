"""Two counters, opt-in, no identifiers that outlive a month.

Downloads are counted; usage is not — a download says nothing about whether the
app was ever unzipped. Andreas wants a base for deciding whether a support
system, a feedback system or a bug reporter is worth building, *"based on data
and not gut feeling"*. Design and the decisions behind it:
docs/superpowers/specs/2026-09-17-usage-telemetry-design.md (local).

Pure: no Qt, no settings object, no clock of its own. Every function takes what
it needs, so the rules can be tested without a window or a network.

THE IDENTITY DECISION, because it is the one that looks wrong at a glance. A
heartbeat with no id at all is privacy-maximal, and it would MISLEAD: astro use
is weather-driven and bursty, so a user who processes on three nights after one
clear spell makes daily-actives read 5 where the real monthly base is 60 — and
"nobody uses this" is the wrong conclusion to hand someone deciding what to
build. So there is an id, and it is REGENERATED EVERY CALENDAR MONTH: distinct
installs countable within a month, nothing linkable across months. It is a
pseudonymous identifier while it lives; the privacy page says so in those words
rather than claiming "anonymous".
"""
from __future__ import annotations

import datetime
import json
import urllib.request
import uuid

# nocturneastro.com since 2026-09-20. nocturne.stehn.com still SERVES this
# endpoint and always will: every build from 0.32 to 0.36 posts here, and that
# host redirects everything EXCEPT /ping.php for exactly that reason — urllib
# turns a POST into a GET when it follows a 301, so a redirect would leave old
# clients posting nothing while appearing to work.
PING_URL = "https://nocturneastro.com/ping.php"

# The closed set. A field not in here cannot be sent, and `build_payload` is
# checked against it — each extra field narrows the crowd a user hides in, and
# at this user-base size (dozens, maybe low hundreds) three or four of them can
# make one person unique. `os` was in the first draft and was dropped: Nocturne
# ships macOS only, so nothing would ever have been decided from it.
ALLOWED_KEYS = frozenset({"event", "version", "id"})
EVENTS = ("first-run", "daily")

# settings.telemetry, which is deliberately three-valued. "unset" is what the
# first-run question keys on, so "not asked yet" can never be mistaken for "no".
UNSET, ON, OFF = "unset", "on", "off"


def month_key(day: datetime.date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def rotate_id(current_id: str, current_month: str, today: datetime.date) -> tuple[str, str]:
    """The install id for `today`, and the month it belongs to.

    Returns a NEW id whenever the month differs from the one the current id was
    issued for — including when there is no id yet. Same id within a month, so a
    month's distinct-id count is a count of installs.
    """
    this_month = month_key(today)
    if current_id and current_month == this_month:
        return current_id, current_month
    return uuid.uuid4().hex, this_month


def build_payload(event: str, version: str, install_id: str | None = None) -> dict:
    """The whole protocol. Raises on an unknown event rather than inventing one."""
    if event not in EVENTS:
        raise ValueError(f"unknown telemetry event: {event!r}")
    payload = {"event": event, "version": version}
    if event == "daily":
        payload["id"] = install_id
    extra = set(payload) - ALLOWED_KEYS
    if extra:                                  # unreachable by design, asserted anyway
        raise ValueError(f"payload carries fields outside ALLOWED_KEYS: {sorted(extra)}")
    return payload


def should_send_daily(last_sent: str, today: datetime.date) -> bool:
    """At most one `daily` per calendar day, so the server's count of pings for a
    day IS a count of installs active that day — no de-duplication needed, and no
    finer timestamp than the date ever leaves the machine.

    An unparseable or empty `last_sent` sends: losing a day is worse than the
    alternative of a stuck client that never reports again.
    """
    try:
        return datetime.date.fromisoformat(last_sent) != today
    except (TypeError, ValueError):
        return True


def send(payload: dict, *, opener=urllib.request.urlopen, timeout: float = 10.0) -> bool:
    """POST it once. Returns whether it went. NEVER raises, never retries.

    No retry and no disk queue, both deliberate: a queue would turn a week
    offline into a burst that correlates a user's activity in time — a
    fingerprint by another name — and would mean the app holding data about
    someone it has not sent. A missed day is a missed day.
    """
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            PING_URL, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": f"Nocturne/{payload.get('version', '')}"})
        with opener(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False
