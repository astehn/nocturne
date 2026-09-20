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
    for t in _targets():
        assert t["size"] >= 5.0, t


def test_every_target_has_a_usable_size():
    """No size means framing cannot be reported, so the object is excluded."""
    for t in _targets():
        assert isinstance(t["size"], float) and t["size"] > 0, t


def test_coordinates_are_in_range():
    for t in _targets():
        assert 0.0 <= t["ra"] < 360.0, t
        assert -90.0 <= t["dec"] <= 90.0, t


def test_the_count_is_what_the_spec_says():
    assert len(_targets()) == 158


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
def test_build_records_the_rule_it_actually_applied():
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

    data = build()
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
