import numpy as np
from astropy.io import fits
from seestar_processor.core.image import AstroImage
from seestar_processor.recipe import Recipe
from seestar_processor.settings import Settings
from seestar_processor.batch import apply_recipe, run_batch


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
