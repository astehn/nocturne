"""Pin the zone the app calls "local" for one test.

The POSIX way — TZ in the environment, then time.tzset() — does not exist on
Windows, so tests pin `capture_time.LOCAL_ZONE` instead, which every capture
time the app shows or groups into a night goes through. On Windows ZoneInfo
needs the `tzdata` package (the dev extra installs it there).
"""
from zoneinfo import ZoneInfo

from nocturne.stacking import capture_time


def pin_local_zone(monkeypatch, name: str = "Europe/Stockholm") -> None:
    monkeypatch.setattr(capture_time, "LOCAL_ZONE", ZoneInfo(name))
