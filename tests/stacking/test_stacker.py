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


def test_master_keeps_the_optics_so_the_fov_hint_is_not_assumed(tmp_path):
    """The in-memory master goes straight to open_image, so if it loses the
    optics every downstream scale question falls back to the SEESTAR_S30_PRO
    profile. That was invisible on an S30 Pro — the assumed camera was the
    right one — and wrong by 56% on an S50 (250 mm vs 160 mm focal length),
    which is enough to fail a solve and silently cost SPCC its calibration.

    Asserts the SOURCE, not just the number: a hint that happens to look right
    while coming from a guess is the bug this is guarding."""
    from nocturne.core.instrument import fov_hint

    base = make_star_field(n_stars=40, seed=7)
    s50 = {"FOCALLEN": 250.0, "XPIXSZ": 2.9, "OBJECT": "M42"}
    paths = []
    for i in range(4):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"s50_{i}.fit"
        write_color_fits(p, f, exptime=10.0, header=s50)
        paths.append(str(p))

    result = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")))
    meta = result.image.metadata
    assert meta["focal_length"] == 250.0 and meta["pixel_size"] == 2.9
    assert meta["target"] == "M42"

    h = result.image.data.shape[0]
    got, source = fov_hint(meta, h)
    assert source == "header", "the master's own optics were dropped, so the scale was assumed"
    assert got == pytest.approx(206.265 * 2.9 / 250.0 * h / 3600.0, rel=1e-6)


def test_the_master_still_names_its_camera_after_a_save_and_reload(tmp_path):
    """The in-memory master and the same master reloaded from disk must identify
    as the same camera — the two paths a user actually takes (stack then keep
    working, versus stack, restart, reopen). Without INSTRUME in the written
    header the reloaded file falls back to matching on focal length, which is
    fine until two Seestars share one."""
    from nocturne.core.fits_io import load_fits
    from nocturne.core.instrument import identify, SEESTAR_S50

    base = make_star_field(n_stars=40, seed=11)
    s50 = {"FOCALLEN": 250.0, "XPIXSZ": 2.9, "CREATOR": "ZWO Seestar S50"}
    paths = []
    for i in range(4):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"cam{i}.fit"
        write_color_fits(p, f, exptime=10.0, header=s50)
        paths.append(str(p))

    out = str(tmp_path / "named.fits")
    result = run_stack(StackOptions("average", 2.5, paths, out))
    assert identify(result.image.metadata) is SEESTAR_S50, "in-memory master lost its camera"

    reloaded = load_fits(out)
    assert reloaded.metadata.get("instrument") == "ZWO Seestar S50"
    assert identify(reloaded.metadata) is SEESTAR_S50, "reloaded master lost its camera"


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
    full = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "f.fits"),
                                  autocrop=False))
    cropped = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "c.fits"),
                                     autocrop=True))
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
    integ = [c for c in calls if "combining" in c[2]]
    # one progress tick per used frame, reaching the total
    assert len(integ) == 4
    assert [c[0] for c in integ] == [1, 2, 3, 4]
    assert all(c[1] == 4 for c in integ)


def test_progress_numbers_the_phases_so_a_refilling_bar_reads_as_progress(tmp_path):
    """The bar restarts once per phase. Reaching 100% and starting over with no
    explanation reads as a hang, so every label carries "Step N of M" — and M
    must match the number of phases the chosen method actually runs, which only
    run_stack knows (sigma-clip walks the frames twice, average once)."""
    paths = _make_subs(tmp_path)

    def labels_for(method):
        calls = []
        run_stack(StackOptions(method, 2.5, paths, str(tmp_path / f"{method}.fits")),
                  on_progress=lambda i, n, label: calls.append(label))
        return calls

    avg = set(labels_for("average"))
    assert avg == {"Step 1 of 2 — aligning frames", "Step 2 of 2 — combining frames"}

    sig = set(labels_for("sigma_clip"))
    assert sig == {"Step 1 of 3 — aligning frames",
                   "Step 2 of 3 — combining frames",
                   "Step 3 of 3 — combining frames"}, \
        "sigma-clip runs two integration passes and must say so"


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


def test_run_stack_cancels_via_ambient_token(tmp_path):
    from nocturne.core.tasks import CancelToken, Cancelled, set_ambient, clear_ambient
    paths = _make_subs(tmp_path)
    opts = StackOptions("average", 2.5, paths, str(tmp_path / "master.fits"))
    tok = CancelToken()
    tok.cancel()
    set_ambient(tok)
    try:
        with pytest.raises(Cancelled):
            run_stack(opts)
    finally:
        clear_ambient()


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


def test_master_header_carries_filter():
    from nocturne.stacking.stacker import master_header
    h = master_header({"filter": "LP"}, count=5, integ=100.0)
    assert h["FILTER"] == "LP"
    # no filter available -> no FILTER card, no crash
    assert "FILTER" not in master_header({"frames": 3}, 3, 60.0)


def test_frames_with_different_sky_levels_are_normalized_before_combining(tmp_path):
    """That normalize.py is correct means nothing if run_stack does not call it.
    Deleting the call passed the entire suite until this existed.

    Half these frames carry a much brighter sky. Un-normalized, the master's
    background lands between the two levels; normalized, every frame is brought
    to the reference's level and the master keeps the reference's sky-to-star
    ratio. The ratio rather than an absolute, because run_stack divides the
    master by its peak at the end.
    """
    base = make_star_field(n_stars=40, seed=5)
    paths = []
    for i in range(8):
        f = base.copy()
        if i >= 4:
            f = f + 0.30                      # a much brighter sky, same stars
        p = tmp_path / f"sky{i}.fit"
        write_color_fits(p, f.astype(np.float32), exptime=10.0)
        paths.append(str(p))

    r = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "sky.fits"),
                               autocrop=False))
    d = r.image.data
    got = float(np.median(d) / d.max())

    ref = base
    normalized = float(np.median(ref) / ref.max())          # every frame at ref level
    unnormalized = float(np.median(ref + 0.15) / (ref + 0.15).max())   # averaged levels

    assert abs(got - normalized) < abs(got - unnormalized), (
        f"sky/peak {got:.4f} is closer to the un-normalized {unnormalized:.4f} "
        f"than to the normalized {normalized:.4f} — run_stack is not normalizing")


def test_stack_result_reports_the_peak_it_divided_by(tmp_path):
    """A mosaic averages panel masters together, and run_stack normalises each
    one by ITS OWN peak — so two panels whose brightest star differs land on
    different scales, and averaging them makes a step that reads as a background
    fault. Undoing it needs the divisor, which is otherwise lost."""
    paths = _make_subs(tmp_path)
    result = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")))

    assert result.peak > 0.0
    assert float(result.image.data.max()) == pytest.approx(1.0, abs=1e-6)
    assert float((result.image.data * result.peak).max()) == pytest.approx(
        result.peak, rel=1e-6)


def test_peak_does_not_change_the_master(tmp_path):
    """Assert UNCHANGED, not 'not wrong': the new field must be pure addition."""
    paths = _make_subs(tmp_path)
    a = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "a.fits")))
    before = a.image.data.copy()
    b = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "b.fits")))
    assert np.array_equal(b.image.data, before)
    assert b.frame_count == a.frame_count
    assert b.integration_seconds == a.integration_seconds


def test_the_master_is_bit_identical_whatever_the_worker_count(tmp_path, monkeypatch):
    """The master must not depend on how many workers produced it.

    Be clear about what this DOES catch, because an earlier version of this
    docstring claimed more. It does NOT verify frame ordering: measured, the
    integrators are order-insensitive at realistic scales, and reversing the
    frames leaves the master bit-identical. Mutation-tested — reversing the
    order leaves this test green.

    What it does catch, verified by mutation, is a frame being DROPPED or
    DUPLICATED by the pool, which is the realistic failure of a parallel
    pipeline and which changes the master immediately.

    np.array_equal, not allclose: 'nearly the same master' is the bug.
    """
    from nocturne.stacking import parallel, stacker
    paths = _make_subs(tmp_path, n=6, seed=5)

    masters = {}
    for n in (1, 2, 5):
        monkeypatch.setattr(
            stacker, "plan_workers",
            lambda n=n: parallel.WorkerPlan(count=n, limiter="test", cores=n, ram_gb=64.0))
        out = tmp_path / f"m{n}.fits"
        masters[n] = run_stack(
            StackOptions("sigma_clip", 2.5, paths, str(out))).image.data

    assert np.array_equal(masters[1], masters[2]), "2 workers changed the master"
    assert np.array_equal(masters[1], masters[5]), "5 workers changed the master"


def test_parallel_stacking_matches_the_serial_implementation(tmp_path, monkeypatch):
    """Assert-UNCHANGED against one worker, which IS the old serial path.

    Written this way rather than 'the master looks plausible': a parallel
    implementation that quietly dropped or double-counted a frame would still
    produce a plausible-looking master.
    """
    from nocturne.stacking import parallel, stacker
    paths = _make_subs(tmp_path, n=5, seed=9)

    def _plan(n):
        return lambda: parallel.WorkerPlan(count=n, limiter="test", cores=n, ram_gb=64.0)

    monkeypatch.setattr(stacker, "plan_workers", _plan(1))
    serial = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "a.fits")))
    monkeypatch.setattr(stacker, "plan_workers", _plan(4))
    par = run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "b.fits")))

    assert np.array_equal(serial.image.data, par.image.data)
    assert serial.used == par.used, "the frames used, and their order, must match"
    assert serial.frame_count == par.frame_count
    assert serial.integration_seconds == par.integration_seconds


def test_progress_still_counts_every_frame_once_in_order(tmp_path, monkeypatch):
    """Progress is reported when a result is CONSUMED, not when it is submitted,
    so a parallel pool must not scramble or duplicate the count. A bar that
    jumps around reads as a fault even when the stack is fine."""
    from nocturne.stacking import parallel, stacker
    monkeypatch.setattr(
        stacker, "plan_workers",
        lambda: parallel.WorkerPlan(count=4, limiter="test", cores=4, ram_gb=64.0))
    paths = _make_subs(tmp_path, n=6, seed=3)
    seen = []
    run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")),
              on_progress=lambda i, n, label=None: seen.append((i, label)))
    combining = [i for i, label in seen if label and "combining" in label]
    assert combining == list(range(1, 7)), combining
