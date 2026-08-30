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


def test_a_light_polluted_target_is_in_the_test_split():
    """The design's own requirement: a Bortle 6-7 target in TEST, because both
    val and test were dark-sky while most users are not.

    NGC281 filled that role until 2026-08-30, when it moved to TRAIN for its
    recovered 1514 frames -- the disk loss left IC 1396A as the archive's only
    deep group and the injection premise needs a clean target. NGC7000 is the
    archive's other Helsingborg target (SITELAT 56.150 against Crete's 35.3-35.5)
    and takes the role at a comparable 186 frames to NGC6888's 183.

    The requirement is unchanged; only which target satisfies it moved."""
    _, _, test = D.split_by_target([_tile("NGC7000")], "s30")
    assert [t.target for t in test] == ["NGC7000"]
    train, _, _ = D.split_by_target([_tile("NGC281")], "s30")
    assert [t.target for t in train] == ["NGC281"], "NGC281 now trains"


def test_test_split_still_contains_the_v1_reference_target():
    """NGC6888 has been the reference holdout since v1 so per-target metrics stay
    comparable across runs on exactly the same dark-sky target. Whatever else
    moves, it does not."""
    assert "NGC6888" in D.S30_TEST


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
    would quietly change what every per-target metric is compared against.

    Changed once, deliberately, on 2026-08-30: NGC281 -> NGC7000, so NGC281's
    1514 frames could train. See the v4 note in data.py."""
    assert D.S30_TEST == ("NGC6888", "NGC7000")


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


# ------------------------------------------------- the generating dataset
#
# These tiles are manufactured in the fixture the way build_injection.py
# manufactures them from real frames: a target that is a `depth`-frame stack
# carrying its own residual noise, and four noise fields each with the noise of
# a HALF stack, i.e. sqrt(2) times as much. Anything else and the depth->sigma
# arithmetic under test would be checked against a fiction.

import numpy as np


def _injection_tile(path, *, depth=400, size=256, sigma=0.0006, seed=0, ramp=False):
    rng = np.random.default_rng(seed)
    level = np.full((size, size, 3), 0.05, np.float32)
    amp = np.ones((1, size, 1), np.float32)
    if ramp:
        # A gradient in ONE axis, in both the scene and the noise amplitude, so
        # a field rotated differently from its target is visible as a loss of
        # correlation rather than needing to be reasoned about.
        level = level + np.linspace(0.0, 0.02, size, dtype=np.float32)[None, :, None]
        amp = (0.4 + 1.2 * np.linspace(0.0, 1.0, size, dtype=np.float32))[None, :, None]
    target = level + (rng.normal(0, sigma, level.shape) * amp).astype(np.float32)
    fields = (rng.normal(0, sigma * np.sqrt(2.0), (4, size, size, 3))
              * amp[None]).astype(np.float32)
    np.savez(path, target=target, fields=fields.astype(np.float32),
             coverage=np.ones((size, size), np.float32), depth=np.int32(depth))
    return str(path)


def test_the_injection_dataset_hits_the_requested_depth_band(tmp_path):
    """70% of examples must land in 200-500 frames, where his masters live.
    Both previous models failed because of WHICH examples dominated: the first
    saw mostly shallow stacks and over-corrected, the second mostly deep ones
    and went timid. This proportion is the direct control on that."""
    from data import DataConfig, InjectionDataset

    tile = _injection_tile(tmp_path / "t.npz")
    ds = InjectionDataset([tile], DataConfig(crop=128, augment=False), train=True)
    np.random.seed(20260824)     # a proportion test needs a fixed draw
    deep = sum(1 for _ in range(2000) if 200 <= ds.sample_depth() <= 500)
    assert 0.66 <= deep / 2000 <= 0.74, f"deep share was {deep/2000:.3f}, wanted ~0.70"


def test_the_deep_share_constant_is_what_controls_the_mixture(monkeypatch, tmp_path):
    """Proof the number above is load-bearing and not a coincidence of the
    seed: drive it to both ends and every draw must follow."""
    import data as D
    from data import DataConfig, InjectionDataset

    ds = InjectionDataset([_injection_tile(tmp_path / "t.npz")],
                          DataConfig(crop=128, augment=False), train=True)
    np.random.seed(1)
    monkeypatch.setattr(D, "_DEEP_SHARE", 1.0)
    assert all(200 <= ds.sample_depth() <= 500 for _ in range(200))
    monkeypatch.setattr(D, "_DEEP_SHARE", 0.0)
    assert all(8 <= ds.sample_depth() < 200 for _ in range(200))


def test_a_shallow_group_cannot_claim_a_deep_stack(tmp_path):
    """A 40-frame group's target IS a 40-frame stack. Asking it for a
    300-frame input would demand noise below the target's own floor -- and the
    closer the request gets to the target's depth, the more the 'lesson' is a
    target no cleaner than the input, which is the exact failure this design
    exists to fix. Half the group's depth is where the manufactured input is
    precisely a real half-stack: the deepest claim its own noise field backs."""
    from data import _clamp_depth

    assert _clamp_depth(300, 40) == 20
    assert _clamp_depth(300, 2400) == 300      # a deep group is not clamped
    assert _clamp_depth(8, 40) == 8


def test_every_sample_is_a_supervised_pair_not_an_n2n_one(tmp_path):
    """These have a genuinely cleaner target, so train.py must route them to L1.
    is_n2n=1.0 would send them to L2, which exists for Noise2Noise's conditional
    mean and is not what these need."""
    from data import DataConfig, InjectionDataset

    ds = InjectionDataset([_injection_tile(tmp_path / "t.npz", seed=1)],
                          DataConfig(crop=128, augment=False), train=False)
    item = ds[0]
    assert len(item) == 5
    assert float(item[4]) == 0.0


def test_a_sample_has_the_same_shapes_tiledataset_returns(tmp_path):
    """The 5-tuple goes straight into train.py's existing loop; a different
    layout would be caught only by a shape error hours in, or not at all."""
    from data import DataConfig, InjectionDataset
    from noise import estimate_sigma

    ds = InjectionDataset([_injection_tile(tmp_path / "t.npz", seed=2)],
                          DataConfig(crop=128, augment=False), train=False)
    noisy, clean, mask, sigma, is_n2n = ds[0]
    assert noisy.shape == clean.shape == (3, 128, 128)
    assert mask.shape == (1, 128, 128)
    assert sigma.ndim == 0 and is_n2n.ndim == 0
    # The sigma handed to the conditioning channel is measured on the tile the
    # model is actually given, exactly as TileDataset does it.
    assert abs(float(sigma) - estimate_sigma(noisy.permute(1, 2, 0).numpy())) < 1e-6


def test_the_noisy_side_really_is_noisier_than_the_target(tmp_path):
    """A silent failure to inject would produce identical input and target and
    train a perfect do-nothing model — which is exactly the failure mode of the
    run this design replaces.

    The floor asserted is _MAX_DEPTH_FRACTION's own guarantee: at the clamp the
    input IS a real half-stack of the target, i.e. sqrt(2) = 1.414 times as
    noisy, and no sample may be quieter than that. (The plan's draft compared
    against 1.5x, which only passed because its fixture's target was perfectly
    noiseless -- against a target carrying real residual noise, as every real
    one does, the deepest permitted sample sits at exactly 1.414.)"""
    from data import DataConfig, InjectionDataset

    ds = InjectionDataset([_injection_tile(tmp_path / "t.npz", seed=3)],
                          DataConfig(crop=128, augment=False), train=True)
    np.random.seed(3)
    ratios = []
    for _ in range(20):
        noisy, clean, _, _, _ = ds[0]
        ratios.append(float(noisy.std()) / float(clean.std()))
    assert min(ratios) > 1.35, f"quietest sample was only {min(ratios):.2f}x"
    assert max(ratios) > 3.0, f"noisiest sample was only {max(ratios):.2f}x — the shallow end never fired"


def test_the_injected_noise_matches_the_depth_it_claims(tmp_path, monkeypatch):
    """The whole knob is 'this looks like an n-frame stack'. If the achieved
    sigma does not follow sqrt(n), the fourth channel is being told one thing
    while the pixels say another -- and noise.py's docstring is explicit that
    training and inference must be told the same number."""
    import data as D
    from data import DataConfig, InjectionDataset, from_model_space
    from noise import estimate_sigma

    depth = 800
    tile = _injection_tile(tmp_path / "t.npz", depth=depth, seed=4)
    ds = InjectionDataset([tile], DataConfig(crop=256, augment=False), train=False)
    with np.load(tile) as rec:
        floor = estimate_sigma(rec["target"])
    for claimed in (400, 200, 50, 12):
        monkeypatch.setattr(D.InjectionDataset, "sample_depth",
                            lambda self, rng=None, n=claimed: n)
        noisy, _, _, _, _ = ds[0]
        got = estimate_sigma(from_model_space(noisy.permute(1, 2, 0).numpy()))
        want = floor * np.sqrt(depth / claimed)
        assert abs(got - want) / want < 0.05, (
            f"{claimed} frames: measured {got:.6f}, wanted {want:.6f}")


def test_a_validation_sample_is_the_same_every_time(tmp_path):
    """train.py compares val loss across epochs and keeps the best checkpoint
    by it. A val set that redraws its depth every epoch makes that comparison
    noise, and 'best' becomes 'luckiest'."""
    from data import DataConfig, InjectionDataset

    ds = InjectionDataset([_injection_tile(tmp_path / "t.npz", seed=5)],
                          DataConfig(crop=128), train=False)
    first, second = ds[0], ds[0]
    for a, b in zip(first, second):
        assert np.array_equal(a.numpy(), b.numpy())


def test_augmentation_moves_the_field_with_its_target(tmp_path):
    """Flips and rotations must be applied to the target and the chosen field
    TOGETHER. D carries signal-dependent shot noise tied to the intensities it
    was measured on; rotating one and not the other puts bright-pixel noise
    over dark sky while leaving every shape and every statistic intact."""
    from scipy.ndimage import gaussian_filter

    from data import DataConfig, InjectionDataset, from_model_space

    tile = _injection_tile(tmp_path / "t.npz", seed=6, ramp=True)
    # A crop SMALLER than the tile, so the field must also follow the target's
    # random offset -- not only its rotation.
    ds = InjectionDataset([tile], DataConfig(crop=192, augment=True), train=True)
    np.random.seed(11)
    for _ in range(8):
        noisy, clean, _, _, _ = ds[0]
        lin_n = from_model_space(noisy.permute(1, 2, 0).numpy())
        lin_c = from_model_space(clean.permute(1, 2, 0).numpy())
        added = gaussian_filter(np.abs(lin_n - lin_c).mean(axis=2), 4.0)
        r = np.corrcoef(added.ravel(), lin_c.mean(axis=2).ravel())[0, 1]
        assert r > 0.8, f"injected noise no longer tracks the scene it came from (r={r:.2f})"


def test_the_injected_noise_is_exactly_one_of_the_tiles_own_fields(tmp_path):
    """Exact, not statistical: the difference between the two sides must be a
    scalar multiple of ONE of the four fields this tile carries, cropped at the
    same place as the target. A field taken from the right tile but the wrong
    offset is a plausible-looking bug that every summary statistic survives --
    the noise is still real, still the right size, and no longer over the
    pixels whose brightness produced it."""
    from data import DataConfig, InjectionDataset, from_model_space

    tile = _injection_tile(tmp_path / "t.npz", size=256, seed=8)
    ds = InjectionDataset([tile], DataConfig(crop=128, augment=False), train=False)
    noisy, clean, _, _, _ = ds[0]
    d = (from_model_space(noisy.permute(1, 2, 0).numpy())
         - from_model_space(clean.permute(1, 2, 0).numpy())).ravel()
    with np.load(tile) as rec:
        fields, target = rec["fields"], rec["target"]
    y = x = (256 - 128) // 2                       # the centre crop val uses
    assert np.allclose(from_model_space(clean.permute(1, 2, 0).numpy()),
                       target[y:y+128, x:x+128], atol=1e-6), \
        "the clean side is not this tile's target at the crop it claims"
    best = max(abs(np.corrcoef(d, fields[j][y:y+128, x:x+128].ravel())[0, 1])
               for j in range(len(fields)))
    assert best > 0.999, f"best match to any of the tile's own fields was {best:.4f}"


def test_the_dataset_works_with_only_the_training_dir_on_the_path(tmp_path):
    """train.py puts `training/` on sys.path and nothing else, and `nocturne`
    is not installed into .venv-train -- it is only ever found by path. So a
    module-level import here is not enough: this reproduces train.py's own path
    exactly, from a working directory that is not the repo, and drives a real
    sample through. Without data.py's repo-root insert it dies on the first
    batch, inside a DataLoader worker."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    training_dir = _Path(__file__).resolve().parents[1]
    tile = _injection_tile(tmp_path / "t.npz", seed=9)
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "import data as D\n"
        "ds = D.InjectionDataset([%r], D.DataConfig(crop=128, augment=False), train=False)\n"
        "n, c = ds[0][0], ds[0][1]\n"
        "assert n.shape == c.shape == (3, 128, 128)\n"
        "print('ok')\n" % (str(training_dir), tile)
    )
    proc = subprocess.run([_sys.executable, "-c", script], cwd=tmp_path,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ------------------------------------------- the injection split (Task 6)

def _inj(target, sensor="s30", n=1):
    return [D.InjectionTileRef(path=f"/x/{sensor}_{target}_n/tile_{i:06d}.npz",
                               sensor=sensor, target=target,
                               group=f"{sensor}_{target}_n") for i in range(n)]


def test_no_held_out_target_can_reach_the_injection_split():
    """The second line of defence. build_injection refuses to BUILD these, but
    a stray directory copied in by hand, or a rename, must not be able to put
    Andreas' own test masters into training -- every conclusion this week rests
    on that separation, and nothing else downstream would notice."""
    for held in D.HELD_OUT:
        with pytest.raises(ValueError, match=held):
            D.split_injection_tiles(_inj("M16") + _inj(held), ("s30", "s50"))


def test_the_injection_validation_set_is_m27():
    """M27 validates; NGC7023 moves into TRAINING, unlike the ladder split.
    Its 821 frames are one of only three groups deep enough to give a genuinely
    clean target, and target cleanliness is exactly what its depth now buys."""
    train, val = D.split_injection_tiles(
        _inj("M16") + _inj("M27") + _inj("NGC7023", sensor="s50"), ("s30", "s50"))
    assert [t.target for t in val] == ["M27"]
    assert {t.target for t in train} == {"M16", "NGC7023"}


def test_the_injection_split_refuses_an_empty_side():
    """An empty val set makes 'best checkpoint' meaningless and an empty train
    set trains on nothing; both must fail before the hours, not after."""
    with pytest.raises(ValueError, match="validation|no injection"):
        D.split_injection_tiles(_inj("M16"), ("s30",))
    with pytest.raises(ValueError, match="training|no injection"):
        D.split_injection_tiles(_inj("M27"), ("s30",))


def test_the_injection_split_honours_the_sensor_filter():
    train, val = D.split_injection_tiles(
        _inj("M16") + _inj("M27") + _inj("M42", sensor="s50"), ("s30",))
    assert {t.target for t in train} == {"M16"}
    assert [t.target for t in val] == ["M27"]


def test_scan_injection_tiles_reads_the_layout_build_injection_writes(tmp_path):
    import build_injection

    for slug in ("s30_M16_2026-08-09_LP_10s", "s50_M42_x_IRCUT_20s"):
        (tmp_path / slug).mkdir(parents=True)
        for i in range(2):
            (tmp_path / slug / f"tile_{i:06d}.npz").write_bytes(b"")
    (tmp_path / "injection_manifest.json").write_text("{}")
    found = D.scan_injection_tiles(str(tmp_path))
    assert len(found) == 4
    assert {t.target for t in found} == {"M16", "M42"}
    assert {t.sensor for t in found} == {"s30", "s50"}
    assert build_injection.injection_root({"name": "x"}).name == "injection"
