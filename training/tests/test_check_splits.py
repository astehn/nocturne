import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import check_splits as C  # noqa: E402


# --- name identity ---------------------------------------------------------

def test_the_same_target_under_different_folder_names_is_one_identity():
    """The Seestar recovery renamed everything: the archive holds 'M 8_sub'
    where every split list says 'M8'. Each guard is an exact string compare, so
    all four held-out targets silently became training material — the gate would
    then be judging the model on sky it had learned from and reporting success.
    """
    for variant in ("M8", "M 8", "M 8_sub", "m8_sub", "M_8", " M8 "):
        assert C.canonical(variant) == "m8", f"{variant!r} is not recognised as M8"
    assert C.canonical("NGC281_sub") == C.canonical("NGC 281 LP") == "ngc281"
    assert C.canonical("NGC 6888_sub") == "ngc6888"


def test_canonical_does_not_collapse_genuinely_different_targets():
    """Normalising too hard is the opposite failure: it would quietly merge two
    real targets and hide half the archive."""
    assert C.canonical("M8") != C.canonical("M80")
    assert C.canonical("NGC6992") != C.canonical("NGC6995")
    assert C.canonical("M 31_sub") != C.canonical("M 33_sub")


def test_held_out_names_are_matched_after_normalising():
    held = C.held_out_hits(["M 8_sub", "M 45_sub", "NGC 7000 LP", "NGC 6888_sub",
                            "IC 1396A_sub", "NGC281_sub"])
    assert sorted(held) == ["M 45_sub", "M 8_sub", "NGC 6888_sub", "NGC 7000 LP"]
    assert "IC 1396A_sub" not in held
    assert "NGC281_sub" not in held, "NGC281 trains as of 2026-08-30"


# --- sky identity ----------------------------------------------------------

def test_groups_pointing_at_the_same_sky_are_clustered():
    """Names cannot catch this and no list will: 'MilkyWay' in the archive is
    M 17 shot again — 275.61/-16.15 against 275.60/-16.15. Split those two apart
    and the model is tested on sky it trained on."""
    pointings = {"M 17_sub": (275.60, -16.15),
                 "MilkyWay_sub": (275.61, -16.15),
                 "MilkyWay_timelapse_sub": (275.66, -16.15),
                 "IC 1396A_sub": (324.05, 57.49)}
    clusters = C.sky_clusters(pointings, radius_deg=1.0)
    same = [c for c in clusters if "M 17_sub" in c][0]
    assert same == {"M 17_sub", "MilkyWay_sub", "MilkyWay_timelapse_sub"}
    assert {"IC 1396A_sub"} in clusters


def test_separation_is_measured_on_the_sphere_not_in_degrees_of_ra():
    """At Dec +57 a degree of RA is about half a degree on the sky. Comparing
    raw RA would call two fields adjacent that are not, and — worse — miss two
    that are. IC 1396A and NGC 281 both sit at high declination."""
    near = C.separation_deg((13.65, 56.77), (15.49, 56.77))   # 1.84 deg of RA
    assert near == pytest.approx(1.0, abs=0.05), f"got {near:.3f}"
    equator = C.separation_deg((100.0, 0.0), (101.0, 0.0))
    assert equator == pytest.approx(1.0, abs=0.01)


def test_a_cluster_split_across_two_splits_is_reported():
    pointings = {"M 17_sub": (275.60, -16.15), "MilkyWay_sub": (275.61, -16.15)}
    assignment = {"M 17_sub": "val", "MilkyWay_sub": "train"}
    bad = C.split_collisions(C.sky_clusters(pointings, 1.0), assignment)
    assert bad, "the same sky in train and val must be reported"
    assert {"M 17_sub", "MilkyWay_sub"} == set(bad[0].members)


def test_one_cluster_wholly_inside_one_split_is_fine():
    pointings = {"M 17_sub": (275.60, -16.15), "MilkyWay_sub": (275.61, -16.15)}
    assignment = {"M 17_sub": "train", "MilkyWay_sub": "train"}
    assert C.split_collisions(C.sky_clusters(pointings, 1.0), assignment) == []


def test_an_unassigned_group_is_reported_not_ignored():
    """split_by_target already raises on these, but only once training starts.
    The point of a preflight is to find it in seconds, not two hours in."""
    pointings = {"M 17_sub": (275.60, -16.15)}
    bad = C.split_collisions(C.sky_clusters(pointings, 1.0), {})
    assert bad and bad[0].reason == "unassigned"


def test_the_nas_is_refused_as_a_source(tmp_path):
    """Andreas, 2026-08-30: the NAS must never be written to. It is the backup
    of an archive that has already been lost once, so 'we only read from it' is
    an intention, not a guarantee — a later flag or a typo is all it takes.
    Refusing to point at it at all is the guarantee."""
    for nas in ("/Volumes/Astro", "/Volumes/Astro/M 16_sub", "/Volumes/Images/03-Astro"):
        with pytest.raises(ValueError, match="NAS"):
            C.refuse_nas(nas)


def test_the_local_archive_is_allowed():
    C.refuse_nas("/Volumes/Work/Astro")          # must not raise
    C.refuse_nas("/Volumes/Work/Astro/M 16_sub")


def test_the_test_set_keeps_a_light_polluted_target():
    """NGC281 was held out because it is Helsingborg (Bortle 6-7) while every
    other group is Crete dark sky — testing only on dark sky when most users are
    not is a hole the v2 split note set out to close. Releasing it for its 1514
    frames is only safe because NGC7000 is the archive's other light-polluted
    target. If someone later moves NGC7000 too, this fails rather than quietly
    leaving every holdout dark-sky.

    Sites measured 2026-08-30 from SITELAT: Helsingborg 56.09-56.15,
    Crete 35.34-35.52.
    """
    import data as D
    light_polluted = {"NGC7000", "NGC281"}
    assert set(D.S30_TEST) & light_polluted, (
        f"no light-polluted target left in the test set: {D.S30_TEST}")
    assert set(D.HELD_OUT) & light_polluted, (
        f"no light-polluted target left held out: {D.HELD_OUT}")


def test_the_ladder_and_injection_splits_stay_separate_rules():
    """HELD_OUT overlapping S30_TRAIN looks like a bug and is not: they govern
    DIFFERENT datasets. The ladder path trains on M8 and M45 tiles (S30_TRAIN);
    the injection path must never repeat that exposure, which is what HELD_OUT
    is for. An earlier version of this test asserted they could not overlap and
    would have "fixed" a deliberate design.

    What must actually hold: the three ladder splits are mutually exclusive, and
    nothing held out is used to validate the injection run.
    """
    import data as D
    assert not set(D.S30_TRAIN) & set(D.S30_TEST)
    assert not set(D.S30_TRAIN) & set(D.S30_VAL)
    assert not set(D.S30_VAL) & set(D.S30_TEST)
    assert not set(D.HELD_OUT) & set(D.INJECTION_VAL), (
        "a held-out target cannot also be the injection run's validation set")


def test_every_held_out_name_exists_in_the_archive_naming():
    """A guard that matches nothing is a guard that is off — which is exactly
    how all four held-out targets leaked after the disk loss."""
    import data as D
    archive = ["M 8_sub", "M 45_sub", "NGC 6888_sub", "NGC 7000 LP",
               "NGC281_sub", "IC 1396A_sub", "M 16_sub"]
    canon = {C.canonical(a) for a in archive}
    missing = [h for h in D.HELD_OUT if C.canonical(h) not in canon]
    assert not missing, f"held-out names that match nothing in the archive: {missing}"


def test_the_noise_floor_tool_guards_against_spawn_recursion():
    """macOS spawns rather than forks, so a worker re-imports the script it was
    launched from. Without a __main__ guard every worker re-runs the whole
    experiment inside itself: the first version of this measurement printed its
    banner nine times and burned 30 minutes doing eight recursive copies of the
    work before I noticed. Cheap to assert, expensive to rediscover."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "noise_floor.py"
    text = src.read_text()
    assert '__name__ == "__main__"' in text, "no spawn guard — workers will recurse"
    body = text.split('def main()')[0]
    assert "register_frames(" not in body, "work at import time re-runs in every worker"
