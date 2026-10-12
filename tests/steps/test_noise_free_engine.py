"""The explicit "free" Noise Reduction engine (Auto Enhance presets, 2026-10-11).

Engine None means "RC-Astro, else GraXpert, else built-in", so Auto Enhance on a
GraXpert-only machine ran a ~10-minute GraXpert denoise (668 s of a 746 s run on
a 20 MP master, study 2026-10-11). "free" is the built-in denoise and is never
substituted — not even when GraXpert is installed and a recipe is replayed.
"""
import datetime

import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.core.noise import reduce_noise
from nocturne.recipe import (Recipe, deserialize_option, load_recipe, preflight,
                             save_recipe, serialize_option)
from nocturne.settings import Settings
from nocturne.steps.noise_sharpen import _TV_LEVELS, NoiseSharpenStep


class _Boom:
    """Stands in for NoiseX / GraXpert: reaching one is the failure."""

    def denoise(self, *a, **k):
        raise AssertionError("an external engine ran")


def _img():
    rng = np.random.default_rng(7)
    return AstroImage(rng.random((40, 48, 3)).astype(np.float32), is_linear=False)


def _exe(tmp_path, name):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    p.chmod(0o755)
    return str(p)


FREE = {"engine": "free", "level": "strong"}


def test_free_runs_the_built_in_denoise_even_with_both_tools_present():
    step = NoiseSharpenStep(_Boom(), _Boom())
    img = _img()
    out = step.apply(img, FREE)
    np.testing.assert_array_equal(out.data, reduce_noise(img, _TV_LEVELS["strong"]).data)
    assert step.last_engine == "free"


@pytest.mark.parametrize("rc", [False, True])
@pytest.mark.parametrize("gx", [False, True])
def test_engine_that_will_run_honours_free(rc, gx):
    assert NoiseSharpenStep.engine_that_will_run(FREE, has_rcastro=rc, has_graxpert=gx) == "free"


# What every OLD option answered before "free" existed, captured from the code
# on main (37e8a13) — the new value must leave all of these exactly as they were.
_OLD_ANSWERS = {
    # (option, has_rcastro, has_graxpert) -> engine
    ("rcastro", True, True): "rcastro", ("rcastro", True, False): "rcastro",
    ("rcastro", False, True): "graxpert", ("rcastro", False, False): "free",
    ("graxpert", True, True): "graxpert", ("graxpert", True, False): "rcastro",
    ("graxpert", False, True): "graxpert", ("graxpert", False, False): "free",
    (None, True, True): "rcastro", (None, True, False): "rcastro",
    (None, False, True): "graxpert", (None, False, False): "free",
    ("bare", True, True): "rcastro", ("bare", False, True): "graxpert",
    ("bare", False, False): "free",
}


@pytest.mark.parametrize("key", list(_OLD_ANSWERS))
def test_old_options_are_unchanged(key):
    engine, rc, gx = key
    option = "strong" if engine == "bare" else {"engine": engine, "level": "strong"}
    assert NoiseSharpenStep.engine_that_will_run(
        option, has_rcastro=rc, has_graxpert=gx) == _OLD_ANSWERS[key]


class _Rec:
    def __init__(self, tag, calls):
        self.tag, self.calls = tag, calls

    def denoise(self, img, strength, runner=None):
        self.calls.append(self.tag)
        return img


@pytest.mark.parametrize("engine,rc,gx,want", [
    ("rcastro", True, True, ["rc"]), ("rcastro", False, True, ["gx"]),
    ("graxpert", True, True, ["gx"]), ("graxpert", True, False, ["rc"]),
    (None, True, True, ["rc"]), (None, False, True, ["gx"]), (None, False, False, []),
])
def test_old_options_apply_exactly_as_before(engine, rc, gx, want):
    calls = []
    step = NoiseSharpenStep(_Rec("rc", calls) if rc else None, _Rec("gx", calls) if gx else None)
    step.apply(_img(), {"engine": engine, "level": "strong"})
    assert calls == want


def test_free_round_trips_through_a_saved_recipe(tmp_path):
    stored = serialize_option("noise_sharpen", FREE)
    assert stored == FREE
    path = tmp_path / "r.json"
    save_recipe(Recipe(steps=[{"stage": "noise_sharpen", "option": stored}]), str(path))
    back = load_recipe(str(path))
    assert deserialize_option("noise_sharpen", back.steps[0]["option"]) == FREE


def test_free_replays_free_with_graxpert_installed(tmp_path, monkeypatch):
    from nocturne.batch import apply_recipe
    from nocturne.tools.graxpert import GraXpert
    from nocturne.tools.rcastro import RCAstro
    calls = []
    monkeypatch.setattr(GraXpert, "denoise", lambda *a, **k: calls.append("gx"))
    monkeypatch.setattr(RCAstro, "denoise", lambda *a, **k: calls.append("rc"))
    settings = Settings(graxpert_path=_exe(tmp_path, "graxpert"),
                        rcastro_path=_exe(tmp_path, "rc-astro"))
    path = tmp_path / "r.json"
    save_recipe(Recipe(steps=[{"stage": "noise_sharpen",
                               "option": serialize_option("noise_sharpen", FREE)}]), str(path))
    img = _img()
    out = apply_recipe(img, load_recipe(str(path)), settings)
    assert calls == [], "a recorded free denoise replayed on an external engine"
    np.testing.assert_array_equal(out.data, reduce_noise(img, _TV_LEVELS["strong"]).data)


def test_receipt_and_preflight_name_free_as_the_built_in_denoise(tmp_path):
    from nocturne.core.receipt import engine_for
    settings = Settings(graxpert_path=_exe(tmp_path, "graxpert"))
    note = engine_for("noise_sharpen", settings, "free")
    assert note.engine == "Nocturne (built-in denoise)"
    assert note.reason == "" and not note.is_fallback   # chosen, not substituted
    (plan,) = preflight(Recipe(steps=[{"stage": "noise_sharpen", "option": FREE}]), settings)
    assert plan.outcome == "run" and plan.engine == "Nocturne (built-in denoise)"


def test_provenance_report_names_the_built_in_denoise(tmp_path):
    from nocturne.core.provenance import build_report
    settings = Settings(rcastro_path=_exe(tmp_path, "rc-astro"))
    report = build_report([("Noise Reduction", FREE)], {}, app_version="t",
                          date=datetime.date(2026, 10, 11), settings=settings)
    line = [l for l in report.splitlines() if l.startswith("- Noise Reduction:")]
    assert line == ["- Noise Reduction: **Nocturne (built-in denoise)**"]
