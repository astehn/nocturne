"""Auto Enhance presets (spec 2026-10-11-auto-enhance-presets-design.md): one
table of stage lists, the never-GraXpert denoise rule, and failures returned."""
import numpy as np
import pytest

import nocturne.core.auto_enhance as ae
from nocturne.core import nr_models
from nocturne.core.auto_enhance import AutoRun, build_auto_plan, run_auto_plan
from nocturne.core.color import ColorSettings
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import GOLD_BLUE, palette_defaults
from nocturne.recipe import LEVELS_AUTO
from nocturne.settings import Settings
from nocturne.steps.stretch_step import new_stretch_option


def _img(filt="IRCUT"):
    rng = np.random.default_rng(0)
    data = np.clip(0.003 + rng.normal(0, 0.0005, (48, 64, 3)), 0, 1).astype(np.float32)
    meta = {"filter": filt} if filt is not None else {}
    return AstroImage(data, is_linear=True, metadata=meta)


def _exe(tmp_path, name):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return str(p)


@pytest.fixture
def everything(tmp_path):
    return Settings(graxpert_path=_exe(tmp_path, "graxpert"), astap_path=_exe(tmp_path, "astap"),
                    rcastro_path=_exe(tmp_path, "rc-astro"))


def _plan(img, settings, preset):
    return build_auto_plan(img, settings, include_crop=False, preset=preset)


def _head(decon):
    return [("background", "strong"), ("color", ColorSettings(method="photometric")),
            ("deconvolution", decon)]


# ---- the table, exactly ---------------------------------------------------

def test_natural_broadband_with_every_tool(everything):
    assert _plan(_img(), everything, "natural") == _head("medium") + [
        ("stretch", new_stretch_option(0.30)), ("levels", ae.AUTO_LEVELS),
        ("saturation", (0.5, 0.2)), ("green_fringe", 1.0),
        ("noise_sharpen", {"engine": "rcastro", "level": "strong"}),
        ("local_contrast", 0.15), ("star_reduction", 0.30)]


def test_natural_dualband_uses_strong_deconvolution_and_a_lighter_nebula_boost(everything):
    plan = dict(_plan(_img("LP"), everything, "natural"))
    assert plan["deconvolution"] == "strong"
    assert plan["saturation"] == (0.5, 0.1)


def test_unknown_filter_reads_as_broadband(everything):
    plan = dict(_plan(_img(None), everything, "natural"))
    assert plan["deconvolution"] == "medium" and plan["saturation"] == (0.5, 0.2)


def test_vivid(everything):
    assert _plan(_img(), everything, "vivid") == _head("medium") + [
        ("stretch", new_stretch_option(0.40)), ("levels", ae.AUTO_LEVELS),
        ("saturation", (0.6, 0.4)), ("green_fringe", 1.0),
        ("noise_sharpen", {"engine": "rcastro", "level": "strong"}),
        ("local_contrast", 0.30), ("star_reduction", 0.45)]
    # Same saturation on dual-band: the dual-band nebula 0.1 is Natural's.
    assert dict(_plan(_img("LP"), everything, "vivid"))["saturation"] == (0.6, 0.4)


def test_vivid_saturation_stays_at_or_below_the_cap():
    """M 45's reflection nebula went green at 0.65 (study 2026-10-11)."""
    for preset in ae.PRESETS:
        for stage, value in ae.PRESETS[preset]:
            if stage == "saturation":
                for amount, _neb in (value.values() if isinstance(value, dict) else [value]):
                    assert amount <= 0.6


def test_gold_and_blue_on_dualband(everything):
    assert _plan(_img("LP"), everything, "gold_blue") == _head("strong") + [
        ("stretch", new_stretch_option(0.30)), ("levels", ae.AUTO_LEVELS),
        ("green_fringe", 1.0),
        ("noise_sharpen", {"engine": "rcastro", "level": "strong"}),
        ("star_reduction", 0.40), ("narrowband", palette_defaults(GOLD_BLUE))]


def test_gold_and_blue_narrowband_is_the_shipped_default_palette(everything):
    nb = dict(_plan(_img("LP"), everything, "gold_blue"))["narrowband"]
    assert nb.palette == GOLD_BLUE
    assert nb == palette_defaults(GOLD_BLUE)


@pytest.mark.parametrize("filt", ["IRCUT", None])
def test_gold_and_blue_is_refused_on_anything_but_dualband(everything, filt):
    with pytest.raises(ValueError):
        _plan(_img(filt), everything, "gold_blue")


def test_an_unknown_preset_is_refused():
    with pytest.raises(ValueError):
        _plan(_img(), Settings(), "dramatic")


def test_default_preset_is_natural(everything):
    img = _img()
    assert build_auto_plan(img, everything, include_crop=False) == _plan(img, everything, "natural")


def test_nothing_installed_leaves_out_background_and_deconvolution():
    stages = [s for s, _ in _plan(_img(), Settings(), "natural")]
    assert stages == ["color", "stretch", "levels", "saturation", "green_fringe",
                      "noise_sharpen", "local_contrast", "star_reduction"]
    assert ae.stages_left_out(Settings()) == ["background", "deconvolution"]


def test_graxpert_does_not_bring_deconvolution(tmp_path):
    s = Settings(graxpert_path=_exe(tmp_path, "graxpert"))
    stages = [st for st, _ in _plan(_img(), s, "natural")]
    assert "background" in stages and "deconvolution" not in stages
    assert ae.stages_left_out(s) == ["deconvolution"]


def test_star_reduction_precedes_narrowband_as_the_manual_history_does(everything):
    """Narrowband is a toolbar step appended after the processing stages; a
    Narrowband BEFORE Star Reduction would be cut off by a later re-apply."""
    stages = [s for s, _ in _plan(_img("LP"), everything, "gold_blue")]
    assert stages[-2:] == ["star_reduction", "narrowband"]


@pytest.mark.parametrize("preset,filt", [("natural", "IRCUT"), ("vivid", "IRCUT"),
                                         ("gold_blue", "LP")])
def test_every_preset_follows_processing_order(everything, preset, filt):
    from nocturne.ui.pipeline import PROCESSING_ORDER
    idx = [PROCESSING_ORDER.index(s) for s, _ in _plan(_img(filt), everything, preset)
           if s in PROCESSING_ORDER]
    assert idx == sorted(idx) and len(idx) == len(set(idx))


# ---- noise engine: never GraXpert -------------------------------------------

def _models(monkeypatch, *ids, shipped=()):
    ms = [nr_models.NRModel(i, i.upper(), f"/x/{i}.onnx", i in shipped) for i in ids]
    monkeypatch.setattr(nr_models, "available", lambda: list(ms))


def _engine(img, settings):
    return dict(_plan(img, settings, "natural"))["noise_sharpen"]["engine"]


def test_graxpert_only_picks_free(tmp_path):
    assert _engine(_img(), Settings(graxpert_path=_exe(tmp_path, "graxpert"))) == "free"


def test_nothing_installed_picks_free():
    assert _engine(_img(), Settings()) == "free"


def test_rcastro_picks_noisex_even_when_the_preference_is_graxpert(tmp_path):
    s = Settings(rcastro_path=_exe(tmp_path, "rc"), graxpert_path=_exe(tmp_path, "gx"),
                 denoise_engine="graxpert")
    assert _engine(_img(), s) == "rcastro"


def test_an_nr_model_comes_before_any_fallback(tmp_path, monkeypatch):
    _models(monkeypatch, "v20.0")
    assert _engine(_img(), Settings(graxpert_path=_exe(tmp_path, "gx"))) == "nr:v20.0"
    assert _engine(_img(), Settings()) == "nr:v20.0"


def test_the_newest_model_is_picked_and_a_shipped_one_wins(monkeypatch):
    _models(monkeypatch, "v9", "v18", "v20.0")
    assert _engine(_img(), Settings()) == "nr:v20.0"
    _models(monkeypatch, "v9", "v18", "v20.0", shipped=("v9",))
    assert _engine(_img(), Settings()) == "nr:v9"


def test_model_and_rcastro_the_preference_decides(tmp_path, monkeypatch):
    _models(monkeypatch, "v20.0")
    rc, gx = _exe(tmp_path, "rc"), _exe(tmp_path, "gx")
    assert _engine(_img(), Settings(rcastro_path=rc, denoise_engine="rcastro")) == "rcastro"
    assert _engine(_img(), Settings(rcastro_path=rc, denoise_engine="nr:v20.0")) == "nr:v20.0"
    # GraXpert as the preference is ignored here: the model comes first.
    assert _engine(_img(), Settings(rcastro_path=rc, graxpert_path=gx,
                                    denoise_engine="graxpert")) == "nr:v20.0"


@pytest.mark.parametrize("rc", [False, True])
@pytest.mark.parametrize("gx", [False, True])
@pytest.mark.parametrize("model", [False, True])
@pytest.mark.parametrize("pref", ["rcastro", "graxpert"])
def test_graxpert_is_never_the_denoise_engine(tmp_path, monkeypatch, rc, gx, model, pref):
    if model:
        _models(monkeypatch, "v20.0")
    s = Settings(rcastro_path=_exe(tmp_path, "rc") if rc else "",
                 graxpert_path=_exe(tmp_path, "gx") if gx else "", denoise_engine=pref)
    for preset, filt in (("natural", "IRCUT"), ("vivid", "IRCUT"), ("gold_blue", "LP")):
        assert dict(_plan(_img(filt), s, preset))["noise_sharpen"]["engine"] != "graxpert"
        assert dict(_plan(_img(filt), s, preset))["noise_sharpen"]["engine"] is not None


def test_graxpert_only_auto_enhance_never_runs_the_graxpert_denoise(tmp_path, monkeypatch):
    """End to end through run_auto_plan: the GraXpert denoise is never called,
    and Noise Reduction is the built-in result."""
    from nocturne.core.noise import reduce_noise
    from nocturne.steps.noise_sharpen import _TV_LEVELS
    from nocturne.tools.graxpert import GraXpert
    calls = []
    monkeypatch.setattr(GraXpert, "denoise", lambda *a, **k: calls.append("denoise"))
    s = Settings(graxpert_path=_exe(tmp_path, "gx"))
    plan = [st for st in _plan(_img(), s, "natural") if st[0] != "background"]
    run = run_auto_plan(_img(), plan, s)
    assert calls == []
    assert run.failures == []
    i = [n for n, _o, _im in run.results].index("Noise Reduction")
    before = run.results[i - 1][2]
    np.testing.assert_array_equal(run.results[i][2].data,
                                  reduce_noise(before, _TV_LEVELS["strong"]).data)
    assert run.results[i][1] == {"engine": "free", "level": "strong"}
    assert run.engines[i] == "free"


# ---- run_auto_plan reports failures -----------------------------------------

def test_a_failing_stage_is_returned_and_the_rest_still_run(monkeypatch):
    real = ae.make_step

    def make(stage_id, settings, **kw):
        step = real(stage_id, settings, **kw)
        if stage_id == "saturation":
            def boom(img, option):
                raise RuntimeError("StarXTerminator exited with status 3\nlong trace…")
            step.apply = boom
        return step
    monkeypatch.setattr(ae, "make_step", make)
    plan = _plan(_img(), Settings(), "natural")
    run = run_auto_plan(_img(), plan, Settings())
    assert isinstance(run, AutoRun)
    assert run.failures == [("Saturation", "StarXTerminator exited with status 3")]
    names = [n for n, _o, _im in run.results]
    assert "Saturation" not in names
    assert names[names.index("Levels") + 1:] == ["De-green Stars", "Noise Reduction",
                                                 "Local Contrast", "Star Reduction"]
    assert len(run.results) == len(plan) - 1 == len(run.engines)


def test_a_failure_without_a_message_reads_as_its_type(monkeypatch):
    real = ae.make_step

    def make(stage_id, settings, **kw):
        step = real(stage_id, settings, **kw)
        if stage_id == "local_contrast":
            def boom(img, option):
                raise MemoryError()
            step.apply = boom
        return step
    monkeypatch.setattr(ae, "make_step", make)
    run = run_auto_plan(_img(), _plan(_img(), Settings(), "natural"), Settings())
    assert run.failures == [("Local Contrast", "MemoryError")]


def test_no_failures_is_an_empty_list():
    run = run_auto_plan(_img(), _plan(_img(), Settings(), "natural"), Settings())
    assert run.failures == []
    assert [n for n, _o, _im in run.results][-1] == "Star Reduction"


def test_cancel_is_not_a_failure():
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    tok = CancelToken()
    tok.cancel()
    set_ambient(tok)
    try:
        with pytest.raises(Cancelled):
            run_auto_plan(_img(), _plan(_img(), Settings(), "natural"), Settings())
    finally:
        clear_ambient()


def test_gold_and_blue_runs_end_to_end_on_dualband(tmp_path):
    """Free split, built-in denoise: the whole chain lands, Narrowband last."""
    s = Settings()
    img = _img("LP")
    run = run_auto_plan(img, _plan(img, s, "gold_blue"), s)
    assert run.failures == []
    assert [n for n, _o, _im in run.results][-2:] == ["Star Reduction", "Narrowband"]
    assert run.results[-1][1]["palette"] == GOLD_BLUE
