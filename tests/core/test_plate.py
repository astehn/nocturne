"""The Share title plate's text model.

Fixture note: integration comes from `exposure` + `frames`, not the raw FITS
card names — `resolve_integration` normalises those at load. A fixture spelled
`exptime`/`stackcnt` resolves to nothing, and the credit-line assertions below
would then be checking an empty string.
"""
from nocturne.core.plate import PlateText, plate_text
from nocturne.core.share import caption_line


def test_a_solved_image_fills_both_title_slots():
    meta = {"target_designation": "IC 1396A", "target_common": "Elephant's Trunk Nebula",
            "exposure": 10.0, "frames": 2037}
    t = plate_text(meta, "@andreas")
    assert t.designation == "IC 1396A"
    assert t.common == "Elephant's Trunk Nebula"


def test_it_splits_the_joined_form_when_only_that_is_present():
    """Bundles saved before this feature carry only target_solved."""
    t = plate_text({"target_solved": "M 31 · Andromeda Galaxy"}, "")
    assert (t.designation, t.common) == ("M 31", "Andromeda Galaxy")


def test_an_object_header_alone_still_gets_a_common_name():
    """Never plate-solved: OBJECT gives the designation, the catalogue the name."""
    t = plate_text({"target": "NGC 7000"}, "")
    assert (t.designation, t.common) == ("NGC 7000", "North America Nebula")


def test_an_unknown_target_leaves_the_second_slot_empty_rather_than_guessing():
    t = plate_text({"target": "Backyard Fence"}, "")
    assert t.designation == "Backyard Fence"
    assert t.common == ""


def test_no_target_at_all_is_not_an_error():
    t = plate_text({}, "")
    assert (t.designation, t.common) == ("", "")


def test_the_credit_slot_does_not_repeat_the_target():
    """The target now has two slots of its own; leaving it in the credit line
    would print the object name twice."""
    meta = {"target": "NGC 7000", "exposure": 10.0, "frames": 300}
    t = plate_text(meta, "@andreas")
    assert "NGC 7000" not in t.credit
    assert "@andreas" in t.credit
    assert "300 × 10s" in t.credit, "the credit lost the data it exists to carry"


def test_caption_line_is_unchanged_by_default():
    """The Data preset reproduces today's output byte for byte, so this
    function's default behaviour is frozen."""
    meta = {"target": "NGC 7000", "exposure": 10.0, "frames": 300,
            "date": "2026-08-31T22:10:00"}
    assert caption_line(meta, "andreas") == \
        "NGC 7000 · 50m 00s · 300 × 10s · 2026-08-31 · @andreas"


def test_caption_line_can_omit_the_target():
    meta = {"target": "NGC 7000", "exposure": 10.0, "frames": 300}
    line = caption_line(meta, "", include_target=False)
    assert not line.startswith("NGC 7000")
    assert line == "50m 00s · 300 × 10s", "it dropped more than the target"
