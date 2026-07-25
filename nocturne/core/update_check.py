"""Check GitHub for a newer Nocturne release. Fail-silent by design — a missing
network, timeout, rate-limit, or odd response must never break, block, or slow
the app; every failure path returns None / False."""
from __future__ import annotations

import json
import urllib.request

from .. import __version__

RELEASES_API_URL = "https://api.github.com/repos/astehn/nocturne/releases/latest"
DOWNLOAD_URL = "http://nocturne.stehn.com/"


def _parse(v: str) -> tuple[int, int, int] | None:
    try:
        parts = v.strip().lstrip("vV").split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError, AttributeError):
        return None


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse(latest), _parse(current)
    if a is None or b is None:
        return False
    return a > b


def latest_release_version(opener=urllib.request.urlopen) -> str | None:
    """Latest release tag (e.g. 'v0.4.2') from GitHub, or None on any error.
    `opener` is injectable so tests never hit the network."""
    try:
        req = urllib.request.Request(
            RELEASES_API_URL,
            headers={"User-Agent": f"Nocturne/{__version__}",
                     "Accept": "application/vnd.github+json"})
        with opener(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    except Exception:
        return None
