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

def _tile(target, group=None):
    return D.TileRef(
        path=f"/x/{target}/t0.npz",
        group=group or f"s30_{target}_2026-08-09_LP_10s",
        sensor="s30", target=target, input_count=8, target_count=128,
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
