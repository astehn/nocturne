import os
import numpy as np
import pytest
from skimage.transform import SimilarityTransform, warp
from nocturne.stacking.stacker import StackOptions, master_filename, run_stack
from tests.stacking.synthetic import make_star_field, write_color_fits


def _make_subs(tmp_path, n=4, seed=2):
    base = make_star_field(n_stars=40, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"s{i}.fit"
        write_color_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_run_stack_produces_master(tmp_path):
    paths = _make_subs(tmp_path)
    out = tmp_path / "master.fits"
    opts = StackOptions("average", 2.5, paths, str(out))
    result = run_stack(opts)
    assert result.image.is_linear and result.image.data.ndim == 3
    assert result.frame_count == 4
    assert result.integration_seconds == 40.0
    assert os.path.exists(result.output_path)


def _rotated_subs(tmp_path, n=5, seed=3):
    # Subs with real rotation between them, so the covered region is a rotated
    # envelope smaller than a single frame (the alt-az case).
    base = make_star_field(shape=(120, 120), n_stars=60, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(rotation=np.deg2rad(i * 1.5), translation=(i, -i))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"r{i}.fit"
        write_color_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_autocrop_trims_low_coverage_edges(tmp_path):
    paths = _rotated_subs(tmp_path)
    full = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "f.fits")),
                     autocrop=False)
    cropped = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "c.fits")),
                        autocrop=True)
    fh, fw = full.image.data.shape[:2]
    ch, cw = cropped.image.data.shape[:2]
    assert ch <= fh and cw <= fw
    assert ch < fh or cw < fw            # rotation -> something was trimmed
    # metadata reflects the cropped dimensions
    assert cropped.image.metadata["width"] == cw
    assert cropped.image.metadata["height"] == ch


def test_average_emits_per_frame_integration_progress(tmp_path):
    paths = _make_subs(tmp_path)
    calls = []
    run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")),
              on_progress=lambda i, n, label: calls.append((i, n, label)))
    integ = [c for c in calls if c[2] == "integrating"]
    # one progress tick per used frame, reaching the total
    assert len(integ) == 4
    assert [c[0] for c in integ] == [1, 2, 3, 4]
    assert all(c[1] == 4 for c in integ)


def test_sigma_clip_labels_both_integration_passes(tmp_path):
    paths = _make_subs(tmp_path)
    calls = []
    run_stack(StackOptions("sigma_clip", 2.5, paths, str(tmp_path / "m.fits")),
              on_progress=lambda i, n, label: calls.append((i, n, label)))
    labels = {c[2] for c in calls}
    assert "integrating (pass 1/2)" in labels
    assert "integrating (pass 2/2)" in labels
    # each pass ticks per frame up to the total
    p1 = [c[0] for c in calls if c[2] == "integrating (pass 1/2)"]
    assert p1 == [1, 2, 3, 4]


def test_run_stack_reports_unreadable(tmp_path):
    paths = _make_subs(tmp_path)
    bad = tmp_path / "bad.fit"
    bad.write_text("not a fits file")
    opts = StackOptions("average", 2.5, paths + [str(bad)], str(tmp_path / "m.fits"))
    result = run_stack(opts)
    assert any(str(bad) == p for p, _ in result.rejected)
    assert result.frame_count == 4


def test_run_stack_too_few_frames(tmp_path):
    paths = _make_subs(tmp_path, n=2)
    with pytest.raises(ValueError):
        run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")))


def test_run_stack_starless_reference_raises(tmp_path):
    # A starless reference (include[0]) can't align anything -> everything drops.
    starless = tmp_path / "flat.fit"
    write_color_fits(starless, make_star_field(n_stars=0))
    subs = _make_subs(tmp_path, n=3)
    opts = StackOptions("average", 2.5, [str(starless)] + subs, str(tmp_path / "m.fits"))
    with pytest.raises(ValueError):
        run_stack(opts)


def test_run_stack_normalizes_raw_scale_subs(tmp_path):
    # Subs authored in raw ADU (~800), not 0..1. Master must come back normalized to [0,1]
    # with the star preserved (not clipped to a flat frame).
    base = make_star_field(n_stars=40, seed=7) * 800.0
    paths = []
    for i in range(4):
        t = SimilarityTransform(translation=(i * 0.4, -i * 0.4))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"raw{i}.fit"
        write_color_fits(p, f, exptime=10.0)
        paths.append(str(p))
    result = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")))
    assert result.frame_count == 4
    m = result.image.data
    assert 0.9 <= m.max() <= 1.0          # normalized once, to [0,1]
    assert m.max() > 0.5                   # a bright star survived (not a flat/clipped frame)


def test_master_filename_full_info():
    assert master_filename("NGC 7000", 177, 20.0, 3540.0) == "NGC7000_177x20s_59min.fits"


def test_master_filename_sanitizes_target():
    assert master_filename("M 31 / Andromeda", 50, 10.0, 500.0) == \
        "M31Andromeda_50x10s_8min.fits"


def test_master_filename_no_target():
    assert master_filename("", 177, 20.0, 3540.0) == "master_177x20s_59min.fits"


def test_master_filename_no_exposure():
    assert master_filename("NGC 7000", 177, 0.0, 0.0) == "NGC7000_177frames.fits"


def test_master_filename_fractional_exposure():
    assert master_filename("Moon", 100, 0.5, 50.0) == "Moon_100x0.5s_1min.fits"


def test_master_header_carries_astrometry_and_target():
    from nocturne.stacking.stacker import master_header
    ref_meta = {"target": "NGC 7000",
                "solve_cards": {"OBJCTRA": "20 59 15", "FOCALLEN": 160.0, "XPIXSZ": 2.9}}
    h = master_header(ref_meta, count=177, integ=3540.0)
    assert h["STACKCNT"] == 177 and h["NSUBS"] == 177 and h["EXPTIME"] == 3540.0
    assert h["OBJCTRA"] == "20 59 15" and float(h["FOCALLEN"]) == 160.0   # solvable
    assert h["OBJECT"] == "NGC 7000"
    # no astrometry available -> just the stack counts, no crash
    assert master_header({"frames": 3}, 3, 60.0)["STACKCNT"] == 3
