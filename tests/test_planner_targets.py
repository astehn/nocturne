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


@pytest.mark.skipif(not (ROOT / "site").is_dir(), reason="site/ is local-only")
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
    from build_planner_targets import apply_grades, build, read_grades, read_openngc, select_targets

    # INTO tmp_path. Calling build() bare wrote the real site/planner-targets.json,
    # so `pytest` quietly regenerated a deployable file — see build()'s docstring.
    data = build(out=tmp_path / "planner-targets.json")
    rule, targets = data["rule"], data["targets"]
    assert targets

    reselected = apply_grades(select_targets(read_openngc(), rule["min_arcmin"]), read_grades())
    assert [t["id"] for t in targets] == [t["id"] for t in reselected], (
        "the recorded min_arcmin does not reproduce the targets that were written")
    assert all(t["size"] >= rule["min_arcmin"] for t in targets)
    assert rule["requires_name"] is True and all(t["name"].strip() for t in targets)
    # max_arcmin is recorded as None; prove that is a fact about the file and not
    # just a field, by finding something wider than the S30 Pro's 135' short axis.
    assert max(t["size"] for t in targets) > 135.0, (
        "no target exceeds the frame, so an upper bound could have crept back in "
        "without this file's rule looking wrong")
    assert rule["graded"] == "packaging/planner_grades.csv"


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
        # THE TOLERANCE IS BOUNDED. anchor_deg comes from the same hand-typed
        # row this test is checking, so without a ceiling a future row could
        # declare `anchor_deg,90` and pass unconditionally — the guard would
        # still be here and would still mean nothing.
        assert limit <= 2.0, (
            f"{row['designation']} declares a {limit}° anchor; anything looser "
            f"cannot distinguish a typo from a coordinate")
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



@pytest.mark.skipif(not (ROOT / "site").is_dir(), reason="site/ is local-only")
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
    probe = ROOT / "site" / "planner-targets.json.testprobe"
    try:
        b.build(out=probe)
        assert shipped.read_bytes() == before, \
            "build() wrote the shipped catalogue even when told to write elsewhere"
    finally:
        # In a finally, or a failure leaves the probe in the working tree — and
        # site/ is gitignored, so `git status` would never mention it.
        probe.unlink(missing_ok=True)


def test_no_two_targets_show_the_same_name():
    """The public planner renders `name` ALONE — no id, no `common`.

    A pair of objects a few arcminutes apart ranks adjacently, so the list read
    "3. Eyes / 4. Eyes" with nothing to tell them apart. Five names were shared:
    Eastern Veil and Antennae Galaxies always were, and widening the catalogue
    added Eyes, Butterfly Galaxies and Barnard's E Nebula. Found in the
    whole-branch review, 2026-09-24.
    """
    import collections

    names = [t["name"] for t in _targets()]
    dupes = {n: c for n, c in collections.Counter(names).items() if c > 1}
    assert not dupes, f"these names appear on more than one card: {dupes}"


def test_disambiguation_leaves_unique_names_alone():
    """It appends an id only where it has to. Without this the test above is
    satisfied by suffixing EVERY target, which would put "(NGC 7000)" beside
    "North America Nebula" on every card for nothing."""
    by_id = {t["id"]: t for t in _targets()}
    assert by_id["NGC7000"]["name"] == "North America Nebula"
    assert by_id["NGC6992"]["name"] == "Eastern Veil (NGC 6992)"


def test_the_supplement_names_m45_the_way_every_other_messier_is_named():
    """M 45 was the one target added because Andreas said it was missing — and
    for a few minutes it was the only Messier object in the catalogue not called
    "M nn", because the supplement had no `name` column and fell back to
    `common`. It could not be found by the name he asked for, on the page or in
    the admin's search box."""
    by_id = {t["id"]: t for t in _targets()}
    assert by_id["M45"]["name"] == "M 45"
    assert by_id["M45"]["common"] == "Pleiades"


# --- editorial grades (spec 2026-10-03, D1/D4) ------------------------------

def _graded():
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import apply_grades, read_grades
    return apply_grades(_targets(), read_grades())


def test_every_catalogue_target_has_a_grades_row():
    """Widening the catalogue must not ship ungraded targets silently."""
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import apply_grades, read_grades
    grades = read_grades()
    grades.pop("NGC7000")
    with pytest.raises(SystemExit, match="NGC7000"):
        apply_grades(_targets(), grades)


def test_a_grades_row_for_an_unknown_id_fails():
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import apply_grades, read_grades
    grades = read_grades()
    grades["NGC9999"] = {"grade": "Modest", "sky": "dark", "merge_into": "",
                         "name": "", "size": "", "note": ""}
    with pytest.raises(SystemExit, match="NGC9999"):
        apply_grades(_targets(), grades)


def _apply_with(rid, also=None, **change):
    """apply_grades over the real rows with ONE row mutated (`also`: a second)."""
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    from build_planner_targets import apply_grades, read_grades
    grades = read_grades()
    grades[rid] = dict(grades[rid], **change)
    for oid, ochange in (also or {}).items():
        grades[oid] = dict(grades[oid], **ochange)
    return apply_grades(_targets(), grades)


def test_a_merge_into_a_skip_row_fails():
    """B86 is a Skip: nothing would carry B143's photos or name."""
    with pytest.raises(SystemExit, match="B143 merges into B86"):
        _apply_with("B143", merge_into="B86")


def test_a_merge_chain_fails():
    """IC0349 itself merges into M45, so B143 would vanish twice over. IC0349 is
    given a grade and sky so ONLY the chain guard can catch it -- with its real
    blank grade the Skip/blank guard fires first and this test would be hollow."""
    with pytest.raises(SystemExit, match="B143 merges into IC0349"):
        _apply_with("B143", merge_into="IC0349",
                    also={"IC0349": {"grade": "Modest", "sky": "dark"}})


def test_an_unknown_grade_fails():
    with pytest.raises(SystemExit, match="B142 has grade 'Great'"):
        _apply_with("B142", grade="Great")


def test_an_unknown_sky_fails():
    with pytest.raises(SystemExit, match="B142 has sky 'moonless'"):
        _apply_with("B142", sky="moonless")


def test_skips_and_absorbed_ids_are_not_published():
    ids = {t["id"] for t in _graded()}
    for gone in ("NGC2573", "NGC3172", "NGC1049", "NGC0884", "IC4703", "NGC6995"):
        assert gone not in ids, gone
    assert {"NGC0869", "NGC6611", "NGC6992", "NGC7000"} <= ids


def test_every_published_target_carries_a_valid_grade_and_sky():
    for t in _graded():
        assert t["grade"] in ("Showpiece", "Rewarding", "Modest"), t
        assert t["sky"] in ("city", "suburban", "rural", "dark"), t


def test_the_double_cluster_is_one_target_between_its_halves():
    """Review Focus 4: centre between the parts, size covering both."""
    by = {t["id"]: t for t in _targets()}
    h, chi = by["NGC0869"], by["NGC0884"]
    dc = {t["id"]: t for t in _graded()}["NGC0869"]
    assert dc["name"] == "Double Cluster"
    assert dc["also"] == ["NGC0884"]
    assert min(h["ra"], chi["ra"]) < dc["ra"] < max(h["ra"], chi["ra"])
    # h and chi are ~30' apart; each is 10-14' across, so the pair spans > 40'.
    assert dc["size"] > 40, dc["size"]


def test_a_merge_never_shrinks_the_parent():
    """M 31 absorbs M 32 and M 110, which sit inside its 178'."""
    m31 = {t["id"]: t for t in _graded()}["NGC0224"]
    assert m31["size"] >= 177.8
    assert m31["also"] == ["NGC0205", "NGC0221"]


def test_size_and_name_overrides_apply():
    by = {t["id"]: t for t in _graded()}
    assert by["IC2944"]["size"] == 75.0 and by["IC2944"]["name"] == "Running Chicken Nebula"
    assert by["NGC0253"]["name"] == "Sculptor Galaxy"
    assert by["IC0443"]["name"] == "Jellyfish Nebula"


def test_no_two_published_targets_show_the_same_name():
    import collections
    names = collections.Counter(t["name"] for t in _graded())
    assert not {n: c for n, c in names.items() if c > 1}


def test_the_published_count():
    """186 graded rows, 41 of them Skip (Andreas's review, 2026-10-03): 145 cards. Moves only with the CSV."""
    assert len(_graded()) == 145
