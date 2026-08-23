import json

import numpy as np
from astropy.io import fits

import pytest

from nocturne.stacking.frames import load_sub
from nocturne.stacking.normalize import normalize_to
from nocturne.stacking.register import warp_with_validity
from nocturne.training.pairs import (
    PairConfig,
    discover_frame_groups,
    generate_training_pairs,
    materialize_tiles,
    partition_pair,
    prepare_stack,
    scan_training_frames,
)
import nocturne.training.pairs as pairs_module
from tests.stacking.synthetic import make_star_field, write_cfa_fits


def _write_header_only_frame(path, *, sensor="S30", target="M16", date="2026-08-09",
                             exposure=10.0, filter_name="LP", ra=275.1, dec=-13.8):
    data = np.zeros((32, 48), dtype=np.uint16)
    hdu = fits.PrimaryHDU(data)
    hdu.header["TELESCOP"] = "S30 Pro_test" if sensor == "S30" else "S50_test"
    hdu.header["OBJECT"] = target
    hdu.header["DATE-OBS"] = f"{date}T00:00:00"
    hdu.header["EXPTIME"] = exposure
    hdu.header["FILTER"] = filter_name
    hdu.header["RA"] = ra
    hdu.header["DEC"] = dec
    hdu.header["BAYERPAT"] = "GRBG"
    hdu.writeto(path, overwrite=True)


def test_partition_is_deterministic_and_disjoint(tmp_path):
    paths = [str(tmp_path / f"{i}.fit") for i in range(20)]
    a = partition_pair(paths, input_count=5, target_count=10, seed=7)
    b = partition_pair(paths, input_count=5, target_count=10, seed=7)
    assert a == b
    assert set(a[0]).isdisjoint(a[1])
    assert len(a[0]) == 5 and len(a[1]) == 10


def test_scan_and_group_separates_sensor_filter_exposure_and_night(tmp_path):
    for i in range(4):
        _write_header_only_frame(tmp_path / f"s30_{i}.fit")
    for i in range(4):
        _write_header_only_frame(
            tmp_path / f"s50_{i}.fit", sensor="S50", date="2026-08-10",
            exposure=20.0, filter_name="IRCUT", ra=100.0, dec=20.0,
        )
    frames = scan_training_frames(tmp_path)
    assert len(frames) == 8
    groups = discover_frame_groups(tmp_path, min_frames=3)
    assert len(groups) == 2
    assert {(g.sensor, g.filter_name, g.exposure_s, g.night) for g in groups} == {
        ("s30", "LP", 10.0, "2026-08-09"),
        ("s50", "IRCUT", 20.0, "2026-08-10"),
    }


def test_combine_nights_merges_sessions_of_the_same_target(tmp_path):
    """NGC281 is 46 frames one night and 63 the next. Separately neither can
    build a deep target; together they are a usable Bortle 6-7 holdout, which
    the split requires and currently cannot have."""
    for i in range(46):
        _write_header_only_frame(
            tmp_path / f"night1_{i}.fit", target="NGC281", date="2026-07-15",
        )
    for i in range(63):
        _write_header_only_frame(
            tmp_path / f"night2_{i}.fit", target="NGC281", date="2026-07-16",
        )

    apart = discover_frame_groups(tmp_path, target="NGC281")
    assert len(apart) == 2 and sorted(len(g.frames) for g in apart) == [46, 63]

    together = discover_frame_groups(tmp_path, target="NGC281", combine_nights=True)
    assert len(together) == 1
    assert len(together[0].frames) == 109
    assert together[0].night == "2026-07-15..2026-07-16"


def _stub_prepare_stack_dropping_frames(monkeypatch, dropped_paths):
    """Fabricate registration loss without depending on real misaligned data:
    every path except ``dropped_paths`` "registers", so a chosen night can be
    made to lose a controlled fraction of its frames."""
    dropped = set(dropped_paths)

    class _FakePrepared:
        def __init__(self, paths):
            kept = [p for p in paths if p not in dropped]
            self.frames = {p: object() for p in kept}
            self.rejected = tuple((p, "stub") for p in paths if p in dropped)

    def fake_prepare_stack(paths, reference, **kwargs):
        return _FakePrepared(list(dict.fromkeys(paths)))

    monkeypatch.setattr(pairs_module, "prepare_stack", fake_prepare_stack)


def test_combine_nights_warns_when_a_night_loses_most_frames(tmp_path, monkeypatch):
    """A partial rotation mismatch degrades registration for one session
    rather than destroying it outright; the warning must fire on that
    partial loss, not only on losing a night completely."""
    for i in range(10):
        _write_header_only_frame(
            tmp_path / f"night1_{i}.fit", target="NGC281", date="2026-07-15",
        )
    for i in range(10):
        _write_header_only_frame(
            tmp_path / f"night2_{i}.fit", target="NGC281", date="2026-07-16",
        )
    group = discover_frame_groups(tmp_path, target="NGC281", combine_nights=True)[0]
    night2_paths = [f.path for f in group.frames if f.night == "2026-07-16"]
    dropped = night2_paths[2:]  # night2 keeps only 2/10 -> below the warn threshold
    _stub_prepare_stack_dropping_frames(monkeypatch, dropped)

    messages = []
    generate_training_pairs(
        tmp_path, tmp_path / "out", target="NGC281", combine_nights=True,
        on_progress=messages.append,
    )
    warnings = [m for m in messages if m.startswith("WARNING")]
    assert len(warnings) == 1
    assert "2026-07-16" in warnings[0]
    assert "2/10" in warnings[0]


def test_combine_nights_does_not_warn_when_both_nights_mostly_register(tmp_path, monkeypatch):
    """No false alarm when registration succeeds well above the threshold
    for every session (this is what caught the dead-code branch: it never
    exercised the loop that actually decides whether to warn)."""
    for i in range(10):
        _write_header_only_frame(
            tmp_path / f"night1_{i}.fit", target="NGC281", date="2026-07-15",
        )
    for i in range(10):
        _write_header_only_frame(
            tmp_path / f"night2_{i}.fit", target="NGC281", date="2026-07-16",
        )
    group = discover_frame_groups(tmp_path, target="NGC281", combine_nights=True)[0]
    night2_paths = [f.path for f in group.frames if f.night == "2026-07-16"]
    dropped = night2_paths[9:]  # night2 keeps 9/10 -> above the warn threshold
    _stub_prepare_stack_dropping_frames(monkeypatch, dropped)

    messages = []
    generate_training_pairs(
        tmp_path, tmp_path / "out", target="NGC281", combine_nights=True,
        on_progress=messages.append,
    )
    warnings = [m for m in messages if m.startswith("WARNING")]
    assert warnings == []


def test_mosaic_group_is_flagged(tmp_path):
    for i in range(4):
        _write_header_only_frame(
            tmp_path / f"m{i}.fit", target="M31", ra=10.0 + i * 2.0, dec=40.0
        )
    group = discover_frame_groups(tmp_path, min_frames=3)[0]
    assert group.mosaic
    assert group.pointing_span_deg > 0.5


def test_materialize_tiles_writes_input_target_and_coverage(tmp_path):
    rng = np.random.default_rng(3)
    noisy = type("Image", (), {"data": rng.random((10, 12, 3), dtype=np.float32)})()
    clean = type("Image", (), {"data": rng.random((10, 12, 3), dtype=np.float32)})()
    coverage = np.ones((10, 12), dtype=np.float32)
    count = materialize_tiles(
        noisy,
        clean,
        coverage,
        tmp_path / "tiles",
        tile_size=8,
        overlap=2,
        min_coverage=0.9,
    )
    files = sorted((tmp_path / "tiles").glob("*.npz"))
    assert count == len(files) and count > 0
    with np.load(files[0]) as tile:
        assert tile["input"].shape[-1] == 3
        assert tile["target"].shape == tile["input"].shape
        assert tile["coverage"].ndim == 2


def test_pair_config_defaults_are_prototype_friendly():
    config = PairConfig()
    assert config.input_counts == (16,)
    assert config.target_count == 128
    assert config.method == "average"


def test_generate_pair_reuses_registration_and_writes_manifest(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    base = make_star_field(shape=(160, 160), n_stars=45, seed=18)
    for i in range(8):
        path = root / f"frame_{i:02d}.fit"
        write_cfa_fits(path, np.roll(base, (i % 2, -(i % 3)), axis=(0, 1)))
        with fits.open(path, mode="update") as hdul:
            header = hdul[0].header
            header["TELESCOP"] = "S30 Pro_test"
            header["OBJECT"] = "Prototype"
            header["DATE-OBS"] = f"2026-08-09T00:00:{i:02d}"
            header["FILTER"] = "LP"
            header["RA"] = 100.0
            header["DEC"] = 20.0

    output = tmp_path / "pairs"
    results = generate_training_pairs(
        root,
        output,
        config=PairConfig(
            input_counts=(3,),
            target_count=3,
            pairs_per_group=1,
            write_tiles=True,
            tile_size=64,
            tile_overlap=8,
            min_tile_coverage=0.0,
        ),
        workers=1,
    )
    assert results and results[0]["pairs"]
    pair = results[0]["pairs"][0]
    assert pair["status"] == "written", pair
    pair_dir = output / results[0]["group"] / "pair_0000_in3_target3"
    manifest = json.loads((pair_dir / "manifest.json").read_text())
    assert manifest["pair"]["disjoint"] is True
    assert manifest["pair"]["shared_reference_excluded"] is True
    assert (pair_dir / "input.fits").exists()
    assert (pair_dir / "target.fits").exists()
    assert list((pair_dir / "tiles").glob("*.npz"))


def _prepared_three_frame_stack(tmp_path):
    """Three registered synthetic frames, for testing PreparedStack.integrate
    on small subsets directly (bypassing prepare_stack's own >=3 source-frame
    floor, which is about the whole group and is unrelated to this)."""
    root = tmp_path / "source"
    root.mkdir()
    base = make_star_field(shape=(96, 96), n_stars=20, seed=3)
    paths = []
    for i in range(3):
        path = root / f"frame_{i:02d}.fit"
        write_cfa_fits(path, np.roll(base, (i % 2, -(i % 2)), axis=(0, 1)))
        paths.append(str(path))
    return prepare_stack(paths, paths[0], workers=1), paths


def test_integrate_average_accepts_a_single_frame(tmp_path):
    """average_integrate is a plain per-pixel mean and is correct even for
    one frame; the ladder needs this rung (see nocturne/training/pairs.py:394
    comment) so it must not be rejected by a floor meant for sigma_clip."""
    prepared, paths = _prepared_three_frame_stack(tmp_path)
    solo = [p for p in paths if p != prepared.reference_path][:1]
    assert len(solo) == 1

    stack = prepared.integrate(solo, method="average", workers=1)

    record = prepared.frames[solo[0]]
    sub = load_sub(solo[0], normalize=False)
    normalized = normalize_to(sub.data, record.stats, prepared.reference_stats)
    warped, valid = warp_with_validity(normalized, record.matrix)
    expected = np.where(valid[..., None] if warped.ndim == 3 else valid, warped, 0.0)
    np.testing.assert_allclose(stack.data, expected.astype(np.float32), atol=1e-5)
    assert stack.used == tuple(solo)


def test_integrate_sigma_clip_still_requires_three_frames(tmp_path):
    """The relaxed floor is method-specific: sigma_clip has nothing to clip
    between with only 2 samples and must keep failing loudly."""
    prepared, paths = _prepared_three_frame_stack(tmp_path)
    two = [p for p in paths if p != prepared.reference_path]
    assert len(two) == 2

    with pytest.raises(ValueError, match="sigma_clip"):
        prepared.integrate(two, method="sigma_clip", workers=1)


def test_a_single_hot_pixel_does_not_set_the_pair_scale():
    """The scale divides both sides of the pair, so it sets the image's
    model-space units and therefore the sigma value fed to the conditioning
    channel -- the exact channel that broke on M8. It must be a property of
    the SCENE. With method='average' (ladder_v1's default) hot pixels survive
    integration, so np.max could already be reading a sensor defect rather
    than a star core; with an equally-noisy Noise2Noise target it could be a
    noise spike."""
    from nocturne.training.pairs import scene_scale

    scene = np.full((64, 64, 3), 0.2, np.float32)
    scene[30:34, 30:34, :] = 0.8          # a real star core, several px across
    clean = scene.copy()
    hot = scene.copy()
    hot[10, 10, 0] = 5.0                  # one hot pixel

    assert scene_scale(hot) == pytest.approx(scene_scale(clean), rel=0.05)
    assert float(np.max(hot)) > 4.0       # proves plain max WOULD have taken it


def test_the_scene_scale_still_tracks_a_real_bright_source():
    """The guard must not be so aggressive it flattens genuine stars -- a
    scale that ignores the brightest real thing in the frame would clip it."""
    from nocturne.training.pairs import scene_scale

    dim = np.full((64, 64, 3), 0.2, np.float32)
    bright = dim.copy()
    bright[28:36, 28:36, :] = 0.9
    assert scene_scale(bright) > scene_scale(dim) * 2.0


def test_the_smallest_corroborated_source_still_sets_the_scale():
    """Two adjacent bright pixels are the least a real source can be, and on
    ladder_v1's own targets the brightest pixel's neighbours run 0.70-0.99 of
    it -- so those peaks are stars, not spikes, and any blanket smoother would
    clip them. Measured 2026-08-23: a 3x3 median would have taken the scale to
    0.70-0.79 of the raw max on every one of the nine ladder_v1 groups. This
    test is what stops that: one corroborating neighbour is enough."""
    from nocturne.training.pairs import scene_scale

    scene = np.full((64, 64, 3), 0.2, np.float32)
    scene[20, 20, 1] = 0.9
    scene[20, 21, 1] = 0.9                # a two-pixel source, fully preserved
    assert scene_scale(scene) == pytest.approx(0.9, rel=1e-4)


def test_the_scene_scale_never_exceeds_the_raw_maximum():
    """It is a floor-under-the-peak guard, not a rescale: nothing may push the
    scale ABOVE the data, or the pair would be silently darkened."""
    from nocturne.training.pairs import scene_scale

    rng = np.random.default_rng(4)
    data = rng.random((48, 48, 3)).astype(np.float32)
    assert scene_scale(data) <= float(np.max(data)) + 1e-6


def test_the_manifest_records_the_raw_max_beside_the_scene_scale(tmp_path):
    """Both numbers, so a later run can tell whether the guard actually fired
    on this pair or whether the two agreed -- which is the only way to know if
    ladder_v1's scales were spike-driven."""
    root = tmp_path / "source"
    root.mkdir()
    base = make_star_field(shape=(160, 160), n_stars=45, seed=18)
    for i in range(8):
        path = root / f"frame_{i:02d}.fit"
        write_cfa_fits(path, np.roll(base, (i % 2, -(i % 3)), axis=(0, 1)))
        with fits.open(path, mode="update") as hdul:
            header = hdul[0].header
            header["TELESCOP"] = "S30 Pro_test"
            header["OBJECT"] = "Prototype"
            header["DATE-OBS"] = f"2026-08-09T00:00:{i:02d}"
            header["FILTER"] = "LP"
            header["RA"] = 100.0
            header["DEC"] = 20.0

    output = tmp_path / "pairs"
    results = generate_training_pairs(
        root,
        output,
        config=PairConfig(input_counts=(3,), target_count=3, pairs_per_group=1),
        workers=1,
    )
    pair_dir = output / results[0]["group"] / "pair_0000_in3_target3"
    scaling = json.loads((pair_dir / "manifest.json").read_text())["pair_scaling"]
    assert "scale_raw_max" in scaling
    assert scaling["scale_raw_max"] >= scaling["shared_clean_peak"]
