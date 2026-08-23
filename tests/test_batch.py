import numpy as np
import pytest
from astropy.io import fits
from nocturne.core.image import AstroImage
from nocturne.recipe import Recipe
from nocturne.settings import Settings
from nocturne.batch import apply_recipe, run_batch


def _fits(path, h=24, w=24):
    fits.PrimaryHDU((np.random.rand(3, h, w) * 1000).astype("uint16")).writeto(str(path))


def test_apply_recipe_runs_inapp_steps():
    img = AstroImage(np.random.rand(20, 20, 3).astype(np.float32))
    r = Recipe(steps=[{"stage": "stretch", "option": 0.6},
                      {"stage": "saturation", "option": 0.4},
                      {"stage": "levels", "option": [0.1, 1.2, 0.9]}])
    out = apply_recipe(img, r, Settings())
    assert out.data.shape == (20, 20, 3)
    assert out.is_linear is False  # stretch ran


def test_apply_recipe_crop_uses_detected_bounds():
    data = np.zeros((40, 50, 3), np.float32)
    data[5:35, 8:45] = 0.4
    r = Recipe(steps=[{"stage": "crop",
                       "option": {"aspect": "Original", "rotate": 0,
                                  "flip_h": False, "flip_v": False}}])
    out = apply_recipe(AstroImage(data), r, Settings())
    assert out.data.shape == (30, 37, 3)


def test_run_batch_writes_outputs_and_reports_failure(tmp_path):
    good = tmp_path / "a.fits"
    _fits(good)
    bad = tmp_path / "b.fits"
    bad.write_text("not fits")
    outdir = tmp_path / "out"
    outdir.mkdir()
    r = Recipe(steps=[{"stage": "stretch", "option": 0.5}])
    results = run_batch(r, [str(good), str(bad)], str(outdir), "PNG", Settings())
    assert len([x for x in results if x["ok"]]) == 1
    assert (outdir / "a.png").exists()
    assert any(not x["ok"] for x in results)


def test_batch_replays_remove_green():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    from nocturne.batch import apply_recipe
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9
    rec = Recipe(steps=[{"stage": "remove_green", "option": ""}])
    out = apply_recipe(AstroImage(data), rec, Settings())
    assert out.data[..., 1].max() <= 0.3 + 1e-6


def test_apply_recipe_replays_rotate_and_flip():
    # Non-square so a 90° rotation is observable as an H/W swap.
    data = np.zeros((20, 30, 3), np.float32)
    data[:, 0, :] = 0.9                      # bright left column (col 0)
    r = Recipe(steps=[{"stage": "rotate", "option": ""}])
    out = apply_recipe(AstroImage(data), r, Settings())
    assert out.data.shape[:2] == (30, 20)    # 90° rotate swapped H and W
    # Direction: after a 90° clockwise rotate the original left column lands in the top row.
    assert float(out.data[0, :, :].mean()) > float(out.data[-1, :, :].mean())

    r2 = Recipe(steps=[{"stage": "flip_h", "option": ""}])
    out2 = apply_recipe(AstroImage(data), r2, Settings())
    assert out2.data.shape[:2] == (20, 30)   # flip keeps shape
    # column 0 became the last column after horizontal flip
    assert float(out2.data[:, -1, :].mean()) > float(out2.data[:, 0, :].mean())

    # Two Rotate entries compound to 180°: shape restored, bright column mirrored to the far side.
    r180 = Recipe(steps=[{"stage": "rotate", "option": ""},
                         {"stage": "rotate", "option": ""}])
    out180 = apply_recipe(AstroImage(data), r180, Settings())
    assert out180.data.shape[:2] == (20, 30)
    assert float(out180.data[:, -1, :].mean()) > float(out180.data[:, 0, :].mean())


def test_run_batch_progress_callback(tmp_path):
    a = tmp_path / "a.fits"
    _fits(a)
    outdir = tmp_path / "out"
    outdir.mkdir()
    seen = []
    run_batch(Recipe(steps=[{"stage": "stretch", "option": 0.5}]),
              [str(a)], str(outdir), "TIFF", Settings(),
              on_progress=lambda i, n, p: seen.append((i, n)))
    assert seen == [(1, 1)]


def test_run_batch_stops_at_the_next_file_when_cancelled(tmp_path):
    # Cancellation lands between files, never mid-file: a half-written export is
    # worse than finishing the frame in flight.
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    a, b = tmp_path / "a.fits", tmp_path / "b.fits"
    _fits(a)
    _fits(b)
    outdir = tmp_path / "out"
    outdir.mkdir()
    token = CancelToken()
    recipe = Recipe(steps=[{"stage": "stretch", "option": 0.5}])

    def on_progress(i, n, path):
        token.cancel()          # cancel after the first file completes

    set_ambient(token)
    try:
        with pytest.raises(Cancelled):
            run_batch(recipe, [str(a), str(b)], str(outdir), "TIFF", Settings(),
                      on_progress=on_progress)
    finally:
        clear_ambient()
    written = sorted(p.name for p in outdir.iterdir())
    assert written == ["a.tiff"], "the in-flight file finishes, the next never starts"


def test_run_batch_without_a_token_is_unaffected(tmp_path):
    from nocturne.core.tasks import clear_ambient
    clear_ambient()
    a = tmp_path / "a.fits"
    _fits(a)
    outdir = tmp_path / "out"
    outdir.mkdir()
    results = run_batch(Recipe(steps=[{"stage": "stretch", "option": 0.5}]),
                        [str(a)], str(outdir), "TIFF", Settings())
    assert results[0]["ok"] is True


def _enhance_img():
    rng = np.random.RandomState(0)
    return AstroImage(rng.uniform(0.1, 0.6, (24, 24, 3)).astype(np.float32), is_linear=False)


def test_apply_recipe_replays_pure_enhance_tap():
    from nocturne.core.enhance import ENHANCE_OPS
    base = _enhance_img()
    rec = Recipe(steps=[{"stage": "enhance", "option": "Boost Red"}])
    out = apply_recipe(base, rec, Settings()).data
    expected = ENHANCE_OPS["Boost Red"](base).data
    assert np.allclose(out, expected, atol=1e-6)


def test_apply_recipe_replays_star_colour_via_free_split():
    from nocturne.core.enhance import star_colour_layers
    from nocturne.core.starless import split_stars
    base = _enhance_img()
    rec = Recipe(steps=[{"stage": "enhance", "option": "Star Colour"}])
    out = apply_recipe(base, rec, Settings()).data
    starless, stars = split_stars(base)
    expected = star_colour_layers(starless, stars).data
    assert np.allclose(out, expected, atol=1e-6)


def test_legacy_recipe_without_enhance_still_runs():
    base = _enhance_img()
    out = apply_recipe(base, Recipe(steps=[]), Settings())
    assert np.allclose(out.data, base.data)


def _stretch() -> Recipe:
    return Recipe(steps=[{"stage": "stretch", "option": 0.5}])


def test_run_batch_never_overwrites_its_own_source(tmp_path):
    # Output folder == input folder, Format=FITS: the destination IS the source.
    # That master is hours of capture and there is no undo, so the file must come
    # out byte-identical — not merely "different from the processed version".
    src = tmp_path / "m42.fits"
    _fits(src)
    before = src.read_bytes()
    results = run_batch(_stretch(), [str(src)], str(tmp_path), "FITS", Settings())
    assert src.read_bytes() == before, "the source master was rewritten"
    assert results[0]["ok"] is False
    assert "overwrite the source file" in results[0]["message"]
    assert "output folder or format" in results[0]["message"]


def test_source_collision_survives_symlinks_dotdot_and_trailing_slashes(tmp_path):
    # A string compare of folder names misses every one of these.
    import os as _os
    indir = tmp_path / "in"
    indir.mkdir()
    src = indir / "a.fits"
    _fits(src)
    before = src.read_bytes()
    link = tmp_path / "elsewhere"
    link.symlink_to(indir, target_is_directory=True)
    for outdir in (str(link), str(indir) + _os.sep, str(indir / "sub" / "..")):
        results = run_batch(_stretch(), [str(src)], outdir, "FITS", Settings())
        assert src.read_bytes() == before, f"source rewritten via {outdir}"
        assert results[0]["ok"] is False, f"collision missed via {outdir}"


def test_a_collision_fails_only_that_file_and_the_batch_carries_on(tmp_path):
    # b.fit exports to b.fits — a different name, so it must still be written.
    a, b = tmp_path / "a.fits", tmp_path / "b.fit"
    _fits(a)
    _fits(b)
    before = a.read_bytes()
    results = run_batch(_stretch(), [str(a), str(b)], str(tmp_path), "FITS", Settings())
    assert a.read_bytes() == before
    assert [r["ok"] for r in results] == [False, True]
    assert (tmp_path / "b.fits").exists()


def test_a_collision_costs_nothing_because_it_is_caught_before_processing(tmp_path):
    # Checked before the recipe runs, not after: a guard that still burns a
    # GraXpert run per file before saying no is most of the cost of the bug.
    src = tmp_path / "m42.fits"
    _fits(src)
    ran = []
    rec = Recipe(steps=[{"stage": "stretch", "option": 0.5}])
    import nocturne.batch as batch_mod
    real = batch_mod.apply_recipe
    batch_mod.apply_recipe = lambda *a, **k: (ran.append(1), real(*a, **k))[1]
    try:
        run_batch(rec, [str(src)], str(tmp_path), "FITS", Settings())
    finally:
        batch_mod.apply_recipe = real
    assert ran == [], "the recipe ran before the collision was noticed"


def test_source_collision_on_a_case_insensitive_filesystem(tmp_path):
    # macOS APFS is case-insensitive by default: m42.FITS and m42.fits are ONE
    # file there, so realpath's case-sensitive compare is not enough on its own.
    probe = tmp_path / "CaseProbe"
    probe.write_text("x")
    insensitive = (tmp_path / "caseprobe").exists()
    src = tmp_path / "m42.FITS"
    _fits(src)
    before = src.read_bytes()
    results = run_batch(_stretch(), [str(src)], str(tmp_path), "FITS", Settings())
    assert src.read_bytes() == before, "the source master was rewritten"
    if insensitive:
        assert results[0]["ok"] is False
        assert "overwrite the source file" in results[0]["message"]
