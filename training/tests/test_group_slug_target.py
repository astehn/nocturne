"""Which target a dataset group belongs to — parsed from its directory name.

Measured against the REAL tiles on 2026-08-30, hours before the first training
run: every group collapsed to "IC" or "M", because the parser took
`(s30|s50)_([^_]+)_` and stopped at the first underscore. That held while
targets were written "M45"; the archive rebuilt off the Seestar writes "M 8_sub",
whose slug is `s30_M_8_sub_...`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import data as D  # noqa: E402


def _inject(root, slugs):
    for slug in slugs:
        os.makedirs(os.path.join(root, slug), exist_ok=True)
        np.savez(os.path.join(root, slug, "tile_000000.npz"), a=np.zeros((4, 4)))
    return str(root)


def _ladder(root, slugs):
    for slug in slugs:
        pd = os.path.join(root, slug, "pair_000")
        os.makedirs(os.path.join(pd, "tiles"), exist_ok=True)
        json.dump({"group": {"target_dir": slug.split("_", 1)[1].rsplit("_", 3)[0]},
                   "pair": {"disjoint": True, "input_count": 32, "target_count": 128}},
                  open(os.path.join(pd, "manifest.json"), "w"))
        np.savez(os.path.join(pd, "tiles", "t0.npz"), a=np.zeros((4, 4)))
    return str(root)


# --- the parser -------------------------------------------------------------

@pytest.mark.parametrize("slug,expected", [
    # the names the archive actually uses today
    ("s30_M_16_sub_2026-08-09_LP_10s", "m16"),
    ("s30_M_8_sub_2026-08-07..2026-08-08_LP_10s", "m8"),
    ("s30_M_27_sub_2026-08-09_LP_10s", "m27"),
    ("s30_IC_1396A_sub_2026-08-11..2026-08-26_LP_10s", "ic1396a"),
    ("s30_NGC_6888_sub_2026-08-11_LP_10s", "ngc6888"),
    ("s30_NGC_7000_LP_2026-07-15_LP_20s", "ngc7000"),
    ("s30_NGC281_sub_2026-08-26..2026-08-27_LP_10s", "ngc281"),
    # and the pre-rebuild spelling, which must keep working
    ("s30_M45_2026-08-10_IRCUT_10s", "m45"),
    ("s50_M31_2026-08-10_IRCUT_10s", "m31"),
])
def test_the_target_survives_underscores_in_its_name(slug, expected):
    assert D.target_from_group_slug(slug) == expected


def test_two_targets_sharing_a_first_word_stay_distinct():
    """The specific damage of the old parser: "M 8" and "M 16" both became "M",
    so a held-out target and a training target were the same string."""
    a = D.target_from_group_slug("s30_M_8_sub_2026-08-07_LP_10s")
    b = D.target_from_group_slug("s30_M_16_sub_2026-08-09_LP_10s")
    assert a != b, "M 8 and M 16 must not collapse to one target"


def test_a_directory_that_is_not_a_group_is_skipped_not_guessed():
    for junk in ("not_a_group_dir", "injection", "reference", "s30_short"):
        assert D.target_from_group_slug(junk) is None


# --- what the broken parse actually cost ------------------------------------

def test_a_held_out_target_in_the_injection_tiles_is_refused(tmp_path):
    """This guard was VACUOUS before the fix. M 8's tiles were planted under it
    and it did not fire — canonical("M") is "m", which is in no HELD_OUT entry.
    M 8 is the deep master the 2026-08-22 model damaged; training on it and then
    judging against it would report success and mean nothing."""
    root = _inject(tmp_path, ["s30_M_8_sub_2026-08-07..2026-08-08_LP_10s",
                              "s30_M_27_sub_2026-08-09_LP_10s",
                              "s30_M_16_sub_2026-08-09_LP_10s"])
    with pytest.raises(ValueError, match="held-out"):
        D.split_injection_tiles(D.scan_injection_tiles(root), ("s30",))


def test_the_injection_validation_set_is_found(tmp_path):
    """With every group parsing to "M", INJECTION_VAL ("M27") matched nothing and
    training died at startup on "without them 'best checkpoint' means nothing"."""
    root = _inject(tmp_path, ["s30_M_16_sub_2026-08-09_LP_10s",
                              "s30_M_17_sub_2026-08-07_LP_10s",
                              "s30_M_27_sub_2026-08-09_LP_10s"])
    train, val = D.split_injection_tiles(D.scan_injection_tiles(root), ("s30",))
    assert {t.target for t in val} == {"m27"}
    assert {t.target for t in train} == {"m16", "m17"}
    assert not ({t.target for t in train} & {t.target for t in val})


def test_the_gate_finds_its_held_out_pairs(tmp_path):
    """The ladder half exists only to give the gate real pairs. With the old
    parser its targets became "NGC" — in no split — and split_by_target raised
    "targets not assigned to any split" after the build."""
    root = _ladder(tmp_path, ["s30_NGC_6888_sub_2026-08-11_LP_10s",
                              "s30_NGC_7000_LP_2026-07-15_LP_20s"])
    train, val, test = D.split_by_target(D.scan_tiles(root), ("s30",))
    assert {t.target for t in test} == {"ngc6888", "ngc7000"}
    assert not train and not val, "only the gate's targets were built"


def test_a_training_target_is_never_filed_as_a_test_target(tmp_path):
    root = _ladder(tmp_path, ["s30_M_16_sub_2026-08-09_LP_10s",
                              "s30_NGC_6888_sub_2026-08-11_LP_10s"])
    train, _, test = D.split_by_target(D.scan_tiles(root), ("s30",))
    assert {t.target for t in train} == {"m16"}
    assert {t.target for t in test} == {"ngc6888"}


def test_the_manifest_wins_over_the_directory_name(tmp_path):
    """A renamed directory must not change which split its tiles land in: the
    manifest records the group as it was built, so it is the authority."""
    slug = "s30_RENAMED_BY_HAND_2026-08-11_LP_10s"
    pd = tmp_path / slug / "pair_000"
    os.makedirs(pd / "tiles")
    json.dump({"group": {"target_dir": "NGC 6888_sub"},
               "pair": {"disjoint": True, "input_count": 32, "target_count": 128}},
              open(pd / "manifest.json", "w"))
    np.savez(pd / "tiles" / "t0.npz", a=np.zeros((4, 4)))
    tiles = D.scan_tiles(str(tmp_path))
    assert {t.target for t in tiles} == {"ngc6888"}


# --- the gate's own labelling ----------------------------------------------

def test_the_gate_labels_two_held_out_targets_distinctly():
    """_pair_identity's docstring warned that a mismatch makes "a gate result
    silently attach to the wrong target", and it did: `^(?:s30|s50)_([^_]+)_`
    returned "NGC" for BOTH "NGC 6888_sub" and "NGC 7000 LP". Verified against
    the real pair directories built 2026-08-30."""
    import nightly as N
    a = N._pair_identity("/d/s30_NGC_6888_sub_2026-08-11_LP_10s/pair_0000_in64_target112")
    b = N._pair_identity("/d/s30_NGC_7000_LP_2026-07-15_LP_20s/pair_0000_in64_target115")
    assert a == ("ngc6888", 64)
    assert b == ("ngc7000", 64)
    assert a[0] != b[0], "the two held-out targets must not share a label"


def test_a_capped_gate_run_still_covers_every_held_out_target():
    """select_gate_pairs round-robins across targets so a budget never skips a
    held-out target. With both collapsing to "NGC" there was one bucket, so a
    cap of 2 took two NGC 6888 pairs and no NGC 7000 at all."""
    import nightly as N
    dirs = [f"/d/s30_NGC_6888_sub_2026-08-11_LP_10s/pair_0000_in{d}_target128" for d in (1, 16, 64)] + \
           [f"/d/s30_NGC_7000_LP_2026-07-15_LP_20s/pair_0000_in{d}_target128" for d in (1, 16, 64)]
    chosen = N.select_gate_pairs(set(dirs), 2)
    assert {N._pair_identity(c)[0] for c in chosen} == {"ngc6888", "ngc7000"}


def test_metrics_history_keys_do_not_collide_between_targets():
    """_save_metrics keys on "target:depth". Two targets reading as "NGC" at the
    same depth overwrite each other, and the next run's report then compares one
    target against the other's previous number."""
    import nightly as N
    keys = {f"{N._pair_identity(d)[0]}:{N._pair_identity(d)[1]}" for d in (
        "/d/s30_NGC_6888_sub_2026-08-11_LP_10s/pair_0000_in1_target128",
        "/d/s30_NGC_7000_LP_2026-07-15_LP_20s/pair_0000_in1_target128")}
    assert len(keys) == 2, f"history keys collide: {keys}"
