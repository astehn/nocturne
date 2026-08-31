"""Paths to disks that no longer exist.

Work2 failed on 2026-08-25 taking the training archive with it. Every reference
to it was a default argument: it parses, it imports, it runs, and it fails only
when something finally reads it. For the gallery rebuild that meant discovering
it at release time; for the training runner it meant building a dataset for two
hours before dying on a missing directory.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Assembled rather than written out, so this file does not match its own search.
DEAD = "/Volumes/" + "Work2"


def test_no_live_module_points_at_the_dead_disk():
    offenders = sorted(
        str(f.relative_to(ROOT))
        for d in ("nocturne", "packaging", "scripts", "tests")
        for f in (ROOT / d).rglob("*.py")
        if f.name != Path(__file__).name and DEAD in f.read_text(errors="ignore"))
    assert not offenders, f"dead {DEAD} paths in: {offenders}"


def test_the_guard_is_looking_for_the_right_thing():
    """A search that matches nothing anywhere is a guard that is off. The
    archived training-v1 tree still contains these paths by design, so the
    pattern must still find them there — proving the search works."""
    archive = ROOT / "archive" / "training-v1"
    if not archive.is_dir():
        return                      # archive removed later; nothing to prove against
    hits = [f for f in archive.rglob("*.py") if DEAD in f.read_text(errors="ignore")]
    assert hits, f"{DEAD} matches nothing even in the archive — the search is broken"
