# tests/test_planner_targets.py
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def _targets():
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import select_targets, read_openngc
    return select_targets(read_openngc(ROOT / "nocturne" / "data" / "openngc.csv"))


def test_every_target_has_a_name():
    """The name requirement IS the curation (spec 5.1).

    Nothing without a common name or a Messier number may be in the file,
    because that is what makes it impossible for `NGC 6820` -- no name, no
    reason to care -- to surface in a top-three recommendation.
    """
    for t in _targets():
        assert t["name"].strip(), t


def test_m31_is_present():
    """Pinned by name, because the first draft of the spec removed it silently.

    The rule was once 5-140 arcmin, capping size at the S30 Pro's 135' short
    axis. That excluded M 31 (178'), the Veil, the California Nebula, the Witch
    Head and the SMC -- the most-photographed target among them. The error was
    treating "bigger than the frame" as unusable when it is a framing fact: M 31
    overflows the short axis and sits fine along the 239' long one.

    A regression that reintroduced an upper bound would change nothing else
    visible, so it is pinned here by name rather than by rule.
    """
    ids = {t["id"] for t in _targets()}
    assert "NGC0224" in ids, "M 31 must be in the catalogue"


def test_no_target_is_smaller_than_the_floor():
    """Against the floor the FILE records, not a literal repeated here.

    The floor moved from 5.0 to 1.0 on 2026-09-24 and this test had its own
    copy of the old number, so it failed for being out of date rather than for
    finding anything. A rule that is recorded in the output is a rule the test
    can read — that is what recording it was for.
    """
    import json
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_planner_targets as b

    data = json.loads((ROOT / "site" / "planner-targets.json").read_text())
    floor = data["rule"]["min_arcmin"]
    assert floor == b.MIN_ARCMIN, (
        f"the file was built with min_arcmin={floor} but the generator now says "
        f"{b.MIN_ARCMIN} — regenerate it")
    for t in data["targets"]:
        assert t["size"] >= floor, t


def test_every_target_has_a_usable_size():
    """No size means framing cannot be reported, so the object is excluded."""
    for t in _targets():
        assert isinstance(t["size"], float) and t["size"] > 0, t


def test_coordinates_are_in_range():
    for t in _targets():
        assert 0.0 <= t["ra"] < 360.0, t
        assert -90.0 <= t["dec"] <= 90.0, t


def test_the_count_is_what_the_spec_says():
    """A tripwire for widening the catalogue by ACCIDENT.

    203 = 187 from OpenNGC at the 1' floor, 14 more named only by
    common_names.csv, and 2 that OpenNGC does not carry at all. Widening it on
    purpose means changing this number in the same commit as the rule, which is
    the point: the count should never move without someone saying why.
    """
    assert len(_targets()) == 203


def test_the_rule_is_recorded_in_the_output():
    """Widening the catalogue is a regenerate with different arguments (spec
    5.1a). The file records which rule produced it so the page can state what
    it contains rather than claiming coverage it does not have."""
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import payload
    p = payload(_targets(), min_arcmin=5.0)
    assert p["rule"]["min_arcmin"] == 5.0
    assert p["rule"]["requires_name"] is True
    assert p["rule"]["max_arcmin"] is None, "there is deliberately no upper bound"


@pytest.mark.skipif(
    not SITE.exists(),
    reason="build() writes into site/, which is decoupled and gitignored",
)
def test_build_records_the_rule_it_actually_applied(tmp_path):
    """The test above only proves `payload()` echoes its own argument back.

    That is worth nothing to a reader of planner-targets.json, which is the
    point of recording the rule at all: the file could declare a 5' floor while
    holding 2' objects, or declare no upper bound while a cap silently removed
    M 31 again, and the assertion above would still pass. `build()` is the one
    that has to pass the SAME rule to select_targets() and to payload(), so this
    re-runs the recorded rule and demands it reproduce the written file exactly.

    If it fails, the file is describing a catalogue it does not contain.
    """
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import build, read_openngc, select_targets

    # INTO tmp_path. Calling build() bare wrote the real site/planner-targets.json,
    # so `pytest` quietly regenerated a deployable file — see build()'s docstring.
    data = build(out=tmp_path / "planner-targets.json")
    rule, targets = data["rule"], data["targets"]
    assert targets

    reselected = select_targets(read_openngc(), rule["min_arcmin"])
    assert [t["id"] for t in targets] == [t["id"] for t in reselected], (
        "the recorded min_arcmin does not reproduce the targets that were written")
    assert all(t["size"] >= rule["min_arcmin"] for t in targets)
    assert rule["requires_name"] is True and all(t["name"].strip() for t in targets)
    # max_arcmin is recorded as None; prove that is a fact about the file and not
    # just a field, by finding something wider than the S30 Pro's 135' short axis.
    assert max(t["size"] for t in targets) > 135.0, (
        "no target exceeds the frame, so an upper bound could have crept back in "
        "without this file's rule looking wrong")


def test_the_file_stays_inside_its_budget():
    """40 KB uncompressed. Asserted so that widening the rule fails loudly
    rather than quietly doubling the weight of the page."""
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import payload
    blob = json.dumps(payload(_targets(), 5.0), separators=(",", ":"))
    assert len(blob) < 40_000, f"{len(blob)} bytes"


# --- the hand-entered supplement -------------------------------------------
#
# packaging/planner_extra_targets.csv exists because OpenNGC is NGC and IC
# only, so M 45 (Melotte 22) could never have been in the planner. Every row
# there is typed by a person, which is a kind of wrong a catalogue cannot be.

def _haversine_deg(ra1, dec1, ra2, dec2):
    """Angular separation, properly — not a flat subtraction.

    RA degrees are not sky degrees: they narrow by cos(dec), so at +57° a naive
    difference overstates the RA gap by nearly a factor of two. A guard that got
    that wrong would pass rows it should reject.
    """
    import math
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dp, dl = p2 - p1, math.radians(ra2 - ra1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


def test_every_hand_entered_target_sits_where_its_anchor_says():
    """A transposed digit moves an object across the sky in silence.

    In a planner that means telling someone to look the wrong way on the one
    clear night they get. So each row names an object that IS in OpenNGC and
    lies nearby, and must fall within `anchor_deg` of it.
    """
    import csv as _csv
    from build_planner_targets import read_extra, read_openngc

    catalogue = {r["name"].strip(): r for r in read_openngc()}
    rows = read_extra()
    assert rows, "the supplement is empty — M 45 has silently left the planner"

    for row in rows:
        anchor = catalogue.get(row["anchor"].strip())
        assert anchor is not None, (
            f"{row['designation']} is anchored to {row['anchor']}, which is not "
            f"in OpenNGC — the anchor must be checkable")
        sep = _haversine_deg(float(row["ra_deg"]), float(row["dec_deg"]),
                             float(anchor["ra_deg"]), float(anchor["dec_deg"]))
        limit = float(row["anchor_deg"])
        assert sep <= limit, (
            f"{row['designation']} is {sep:.2f}° from {row['anchor']}, more than "
            f"the {limit}° it claims — check the coordinates")


def test_the_supplement_never_shadows_the_catalogue():
    """A hand-typed row must not quietly override a catalogued one. OpenNGC is
    the authority wherever it has an opinion; this file is only for holes."""
    from build_planner_targets import read_extra, read_openngc

    catalogued = {r["name"].strip() for r in read_openngc()}
    for row in read_extra():
        d = row["designation"].strip()
        assert d not in catalogued, (
            f"{d} is in OpenNGC already — remove it from the supplement rather "
            f"than maintaining two sources for one object")


def test_the_overlay_supplies_names_openngc_lacks():
    """The generator used to read only OpenNGC's `common` column, so thirteen
    objects with good coordinates were dropped for want of a name that was
    already written down in common_names.csv — including NGC 281 and Sh 2-142,
    both of which were on the wall and could not be promoted anywhere."""
    from build_planner_targets import read_common_names, read_openngc, select_targets

    rows = read_openngc()
    with_overlay = {t["id"] for t in select_targets(rows)}
    without = {t["id"] for t in select_targets(rows, overlay={}, extra=[])}

    assert "NGC0281" in with_overlay, "the Pacman Nebula is still not a target"
    assert "NGC0281" not in without, \
        "NGC0281 no longer needs the overlay — this guard is testing nothing"
    assert len(with_overlay - without) >= 10, \
        "the overlay has stopped contributing targets"


def test_the_overlay_never_outranks_a_catalogue_name():
    """The overlay is colloquial. Where OpenNGC names an object, that wins."""
    from build_planner_targets import _display_name

    row = {"name": "NGC7000", "common": "North America Nebula", "messier": ""}
    assert _display_name(row, {"NGC7000": "Something Else"}) == "North America Nebula"
    # ...and a Messier number outranks both.
    row = {"name": "NGC1952", "common": "Crab Nebula", "messier": "1"}
    assert _display_name(row, {"NGC1952": "Something Else"}) == "M 1"



def test_running_the_suite_does_not_rewrite_the_shipped_catalogue():
    """pytest must not be a way to regenerate a deployable artifact.

    build() wrote site/planner-targets.json unconditionally and a test called
    it, so the file changed whenever the suite ran — and a later --site-only
    rsync would have shipped that without anyone deciding to. Regenerating is
    meant to be a deliberate act; this is what keeps it one.
    """
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_planner_targets as b

    shipped = ROOT / "site" / "planner-targets.json"
    before = shipped.read_bytes()
    b.build(out=ROOT / "site" / "planner-targets.json.testprobe")
    assert shipped.read_bytes() == before, \
        "build() wrote the shipped catalogue even when told to write elsewhere"
    (ROOT / "site" / "planner-targets.json.testprobe").unlink()
