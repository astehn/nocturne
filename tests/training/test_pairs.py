import json

import numpy as np
from astropy.io import fits

from nocturne.training.pairs import (
    PairConfig,
    discover_frame_groups,
    generate_training_pairs,
    materialize_tiles,
    partition_pair,
    scan_training_frames,
)
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
