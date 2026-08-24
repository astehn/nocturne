import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

PAIRS_ROOT = "/Volumes/Work2/Images/Astro/TrainingPairs"


@pytest.mark.skipif(not os.path.isdir(PAIRS_ROOT), reason=(
    f"needs the training-pairs archive at {PAIRS_ROOT} (external volume, not "
    "in git) -- not a code failure if this drive isn't mounted here"))
def test_dataset_reports_the_sigma_of_the_tile_it_returns():
    """Measured on the tile actually handed to the model, not the whole pair --
    a crop from a bright core and a crop from empty sky have different noise."""
    import data as D
    tiles = D.scan_tiles(PAIRS_ROOT)
    ds = D.TileDataset(tiles[:4], D.DataConfig(), train=False)
    noisy, clean, mask, sigma, _is_n2n = ds[0]
    from noise import estimate_sigma
    assert abs(float(sigma) - estimate_sigma(noisy.permute(1, 2, 0).numpy())) < 1e-6
    assert float(sigma) > 0


# ------------------------------------------------- the light-polluted holdout

import data as D

def _tile(target, group=None, sensor="s30"):
    return D.TileRef(
        path=f"/x/{target}/t0.npz",
        group=group or f"{sensor}_{target}_2026-08-09_LP_10s",
        sensor=sensor, target=target, input_count=8, target_count=128,
    )


def test_ngc281_is_assigned_to_a_split():
    """The design's own new requirement: a Bortle 6-7 target in TEST. Task 2
    taught the generator to combine NGC281's two nights precisely so it would
    produce pairs -- but a target that produces tiles and belongs to no split
    makes split_by_target raise, which would take down train.py, evaluate.py
    and nightly.py on the FIRST full ladder build."""
    _, _, test = D.split_by_target([_tile("NGC281")], "s30")
    assert [t.target for t in test] == ["NGC281"]


def test_test_split_still_contains_the_v1_reference_target():
    """NGC281 is added ALONGSIDE NGC6888, not instead of it: per-target metrics
    keep v1/v2/v3 comparable on exactly the same dark-sky holdout."""
    assert "NGC6888" in D.S30_TEST
    assert "NGC281" in D.S30_TEST


def test_every_archive_target_belongs_to_exactly_one_split():
    """Guards the whole failure mode, not just today's instance of it."""
    splits = (D.S30_TRAIN, D.S30_VAL, D.S30_TEST)
    everything = [t for s in splits for t in s]
    assert len(everything) == len(set(everything)), "a target appears in two splits"
    D.split_by_target([_tile(t) for t in everything], "s30")  # must not raise


def test_a_tile_reports_whether_its_pair_was_noise2noise(tmp_path):
    """The loss depends on it: L1 is median-seeking and is correct against a
    genuinely cleaner target, but Noise2Noise needs the MEAN, so an n2n pair
    must be trainable under L2. If the flag does not reach the dataset, every
    pair silently gets the wrong loss and faint signal is pulled down."""
    import numpy as np
    from data import DataConfig, TileDataset, TileRef

    tile = tmp_path / "t.npz"
    np.savez(tile,
             input=np.full((64, 64, 3), 0.05, np.float32),
             target=np.full((64, 64, 3), 0.05, np.float32),
             coverage=np.ones((64, 64), np.float32))
    ref = TileRef(str(tile), "s30", "M8", "s30_M8_x", 395, 64, kind="n2n")
    ds = TileDataset([ref], DataConfig(crop=64, augment=False), train=False)
    assert len(ds[0]) == 5
    assert float(ds[0][4]) == 1.0

    ref_truth = TileRef(str(tile), "s30", "M8", "s30_M8_x", 16, 128, kind="truth")
    ds2 = TileDataset([ref_truth], DataConfig(crop=64, augment=False), train=False)
    assert float(ds2[0][4]) == 0.0


# ------------------------------------------------------- the S50 half of the archive
#
# n2n_v1 trained on 29% of the archive: 5596 of its 8408 frames are S50 and
# were excluded outright. The S50 groups are the deep ones -- M42 2361 frames,
# SH2-142 1357, NGC7023 821 -- which is exactly the depth range the model is
# weakest in. Andreas' ruling (2026-08-23): "different sensors and different
# FOV but still a Seestar", so include them.

def test_split_by_target_can_be_asked_for_more_than_one_sensor():
    """The trap this is here to close: sel filtered on `t.sensor == sensor`,
    so an S50 tile would be BUILT -- hours of registration and stacking -- and
    then silently dropped on the way into the DataLoader."""
    tiles = [_tile("M16"), _tile("M42", sensor="s50")]
    train, _, _ = D.split_by_target(tiles, ("s30", "s50"))
    assert sorted(t.target for t in train) == ["M16", "M42"]


def test_asking_for_one_sensor_still_selects_only_that_sensor():
    """The old default has to keep behaving, or every caller that has not been
    updated starts training on material it never asked for."""
    tiles = [_tile("M16"), _tile("M42", sensor="s50")]
    train, _, _ = D.split_by_target(tiles, "s30")
    assert [t.target for t in train] == ["M16"]
    assert all(t.sensor == "s30" for t in train)


def test_every_s50_archive_target_belongs_to_exactly_one_split():
    """A target that produces tiles but belongs to no split makes
    split_by_target raise, taking down train.py, evaluate.py and nightly.py --
    after the build, not before it."""
    archive = ["M101", "M42", "NGC6995", "NGC7023", "SH2-142"]
    train, val, test = D.split_by_target(
        [_tile(t, sensor="s50") for t in archive], ("s30", "s50"))
    assigned = sorted(t.target for t in train + val + test)
    assert assigned == sorted(archive)


def test_ngc7023_is_the_first_deep_validation_target():
    """821 frames, so its ladder reaches inputs of 128/256/512/756. Every run
    before this one validated on shallow stacks only, which is precisely the
    depth range where the model's benefit was measured to decay to nothing."""
    assert "NGC7023" in D.S50_VAL
    assert "NGC7023" not in set(D.S50_TRAIN) | set(D.S50_TEST)


def test_the_s30_test_split_is_unchanged():
    """Assert-unchanged, not merely 'contains': the untouched holdout is only
    untouched if nothing was added to it either. Adding an S50 target here
    would quietly change what every per-target metric is compared against."""
    assert D.S30_TEST == ("NGC6888", "NGC281")


# ---------------------------------------------------------------- sky overlap

def test_the_veil_nebula_never_straddles_two_splits():
    """NGC6992 (S30) and NGC6995 (S50) are the same nebula imaged with two
    cameras: their FITS pointings are 0.46 degrees apart, well inside a single
    Seestar frame (the S30 Pro's long axis is about 1.3 degrees). Splitting
    them would score the model on sky it had memorised, through a back door no
    comparison of target NAMES can see. NGC6992 is train, so NGC6995 is train.
    """
    assert ("NGC6992", "NGC6995") in D.SAME_SKY
    assert "NGC6992" in D.S30_TRAIN and "NGC6995" in D.S50_TRAIN


def test_no_two_splits_share_sky():
    """Swept over every region, so a future target added to the wrong split is
    caught by the rule rather than by this one example."""
    for region in D.SAME_SKY:
        splits = {D._split_name(t) for t in region} - {None}
        assert len(splits) <= 1, f"{region} is spread across {splits}"


def test_the_overlapping_sky_guard_actually_raises(monkeypatch):
    """Proof the guard has teeth: move one half of the Veil into val and
    split_by_target must refuse, not quietly return a leaking split."""
    monkeypatch.setattr(D, "S50_TRAIN", tuple(t for t in D.S50_TRAIN if t != "NGC6995"))
    monkeypatch.setattr(D, "S50_VAL", D.S50_VAL + ("NGC6995",))
    with pytest.raises(ValueError, match="NGC6995|sky"):
        D.split_by_target([_tile("NGC6992")], ("s30", "s50"))


# --------------------------------------------------------------- the callers

def test_no_caller_narrows_the_split_back_to_one_sensor():
    """split_by_target defaults to "s30" so an un-updated caller does not
    change under it -- which means the widening only reaches training if every
    caller opts in. A caller left on a single --sensor would build the whole
    S50 half of the archive, hours of registration and stacking, and then drop
    every tile of it on the way into the DataLoader.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    callers = []
    for path in sorted(root.glob("*.py")):
        if path.name == "data.py":
            continue
        for m in re.finditer(r"split_by_target\(([^)]*)\)", path.read_text()):
            callers.append((path.name, m.group(1)))

    assert {name for name, _ in callers} >= {"train.py", "evaluate.py", "nightly.py"}, \
        f"a known caller vanished: {sorted({n for n, _ in callers})}"
    for name, argtext in callers:
        assert "sensors" in argtext, f"{name} calls split_by_target({argtext})"


def test_parse_sensors_reads_a_comma_separated_flag():
    assert D.parse_sensors("s30,s50") == ("s30", "s50")
    assert D.parse_sensors(" s30 ") == ("s30",)
    assert D.parse_sensors(("s30", "s50")) == ("s30", "s50")
