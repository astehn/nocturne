"""Noise Reduction running a Nocturne NR model by its stable id (`nr:<id>`).

The model is the 233-byte fixture described in tests/core/test_nr_models.py,
copied into a tmp tray under the names a real delivery uses.
"""
import json
import pathlib
import shutil

import numpy as np
import pytest

from nocturne.core import nr_models
from nocturne.core.image import AstroImage
from nocturne.steps.noise_sharpen import NoiseSharpenStep

pytest.importorskip("onnxruntime")

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "nr" / "tile_noise.onnx"
ODIN = {"space": "stretched", "inputs": 3, "tile": 256, "id": "v20.0", "name": "Odin"}


@pytest.fixture
def tray(tmp_path, monkeypatch):
    shutil.copy(FIXTURE, tmp_path / "v20.0.onnx")
    (tmp_path / "v20.0.json").write_text(json.dumps(ODIN))
    monkeypatch.setattr(nr_models, "TRAY_DIR", str(tmp_path))
    return tmp_path


class _Boom:
    """Stands in for NXT / GraXpert: reaching one is the failure."""

    def denoise(self, *a, **k):
        raise AssertionError("another engine ran")


def _img():
    rng = np.random.default_rng(3)
    return AstroImage(rng.random((300, 300, 3)).astype(np.float32), is_linear=False)


def test_nr_engine_runs_the_model_at_the_level_strength(tray):
    step = NoiseSharpenStep(_Boom(), _Boom())
    img = _img()
    out = step.apply(img, {"engine": "nr:v20.0", "level": "medium"})
    want = nr_models.denoise(img, 0.75, nr_models.find("v20.0"))
    np.testing.assert_array_equal(out.data, want.data)
    assert step.last_engine == "NR:v20.0"
    assert not np.array_equal(out.data, img.data)


def test_levels_are_the_contracts():
    from nocturne.steps.noise_sharpen import _NR_LEVELS
    assert _NR_LEVELS == {"light": 0.50, "medium": 0.75, "strong": 1.00}


def test_review_focus_4_a_missing_model_fails_loudly_not_another_engine(tray):
    (tray / "v20.0.onnx").unlink()
    step = NoiseSharpenStep(_Boom(), _Boom())
    img = _img()
    before = img.data.copy()
    step.last_engine = None
    with pytest.raises(FileNotFoundError, match=r"^Nocturne NR v20\.0 is not installed$"):
        step.apply(img, {"engine": "nr:v20.0", "level": "medium"})
    assert step.last_engine is None, "nothing claims to have run"
    np.testing.assert_array_equal(img.data, before)


def test_with_no_external_tools_a_missing_model_does_not_fall_back_to_tv(tray):
    (tray / "v20.0.onnx").unlink()
    with pytest.raises(FileNotFoundError):
        NoiseSharpenStep(None, None).apply(_img(), {"engine": "nr:v20.0", "level": "light"})


def test_the_engine_that_will_run_is_the_model():
    opt = {"engine": "nr:v20.0", "level": "medium"}
    assert NoiseSharpenStep.engine_that_will_run(opt, has_rcastro=False, has_graxpert=True) == "nr"


def test_a_recipe_naming_a_missing_model_fails_with_the_message(tray):
    from nocturne.batch import apply_recipe
    from nocturne.recipe import Recipe, preflight
    from nocturne.settings import Settings
    recipe = Recipe(steps=[{"stage": "noise_sharpen",
                            "option": {"engine": "nr:v20.0", "level": "strong"}}])
    [plan] = preflight(recipe, Settings())
    assert (plan.outcome, plan.engine) == ("run", "Nocturne NR — Odin (v20.0)")
    (tray / "v20.0.onnx").unlink()
    [plan] = preflight(recipe, Settings())
    assert (plan.outcome, plan.reason) == ("fail", "Nocturne NR v20.0 is not installed")
    with pytest.raises(FileNotFoundError, match="Nocturne NR v20.0 is not installed"):
        apply_recipe(_img(), recipe, Settings())


def test_the_report_names_the_model(tray):
    import datetime
    from nocturne.core.provenance import build_report
    from nocturne.settings import Settings
    entries = [("Stretch", {"amount": 0.3, "linked": True}),
               ("Noise Reduction", {"engine": "nr:v20.0", "level": "medium"})]
    rep = build_report(entries, {}, app_version="x", date=datetime.date(2026, 10, 6),
                       settings=Settings())
    assert "2. Noise Reduction — Nocturne NR — Odin (v20.0)" in rep
    assert "- Noise Reduction: **Nocturne NR — Odin (v20.0)**" in rep
    assert "NoiseXTerminator" not in rep and "built-in denoise" not in rep
    assert "- engine: nr:v20.0" in rep, "the parameters keep the stored id"
    (tray / "v20.0.onnx").unlink()
    rep = build_report(entries, {}, app_version="x", date=datetime.date(2026, 10, 6),
                       settings=Settings())
    assert "2. Noise Reduction — Nocturne NR — v20.0" in rep
    assert "- Noise Reduction: **Nocturne NR — v20.0**" in rep
