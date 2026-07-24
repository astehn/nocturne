import numpy as np

from nocturne.core.auto_enhance import build_auto_plan, detect_data_type, run_auto_plan
from nocturne.core.image import AstroImage
from nocturne.settings import Settings


def _stages(plan):
    return [sid for sid, _ in plan]


def _broadband_stack():
    """OSC linear AstroImage with a broadband filter tag."""
    rng = np.random.default_rng(0)
    data = (0.003 + rng.normal(0, 0.0005, (48, 64, 3))).astype(np.float32)
    data = np.clip(data, 0.0, 1.0)
    return AstroImage(data, is_linear=True, metadata={"filter": "IRCUT"})


def _dualband_stack():
    """OSC linear AstroImage with the Seestar LP (dual-band) filter tag."""
    rng = np.random.default_rng(1)
    data = (0.003 + rng.normal(0, 0.0005, (48, 64, 3))).astype(np.float32)
    data = np.clip(data, 0.0, 1.0)
    return AstroImage(data, is_linear=True, metadata={"filter": "LP"})


def test_lp_filter_is_dualband():
    assert detect_data_type({"filter": "LP"}) == "dualband"
    assert detect_data_type({"filter": "lp"}) == "dualband"       # case-insensitive


def test_other_filter_is_broadband():
    assert detect_data_type({"filter": "IRCUT"}) == "broadband"
    assert detect_data_type({"filter": "UV/IR"}) == "broadband"


def test_absent_filter_is_unknown():
    assert detect_data_type({}) == "unknown"
    assert detect_data_type({"filter": ""}) == "unknown"


def test_broadband_plan_shape():
    img = _broadband_stack()
    plan = build_auto_plan(img, Settings(), data_type="broadband")
    s = _stages(plan)
    assert s[0] == "crop" and "color" in s and "stretch" in s
    assert "levels" in s and "noise_sharpen" in s and "saturation" in s
    # aggressive steps excluded from the default
    assert "deconvolution" not in s and "star_reduction" not in s
    assert "green_fringe" not in s and "local_contrast" not in s
    assert "curves" not in s and "recover_core" not in s


def test_broadband_plan_uses_photometric_color_when_astap_available(tmp_path):
    astap = tmp_path / "astap"
    astap.write_text("#!/bin/sh\n")
    astap.chmod(0o755)
    settings = Settings(astap_path=str(astap))
    plan = build_auto_plan(_broadband_stack(), settings, data_type="broadband")
    options = dict(plan)
    assert options["color"].method == "photometric"


def test_broadband_plan_uses_sky_color_without_astap():
    plan = build_auto_plan(_broadband_stack(), Settings(), data_type="broadband")
    options = dict(plan)
    assert options["color"].method == "sky"


def test_dualband_plan_uses_colourise():
    img = _dualband_stack()
    plan = build_auto_plan(img, Settings(), data_type="dualband")
    s = _stages(plan)
    assert "crop" in s
    assert "narrowband" in s          # the Colourise/HOO engine, not plain color+stretch
    assert "color" not in s
    # narrowband requires an already-stretched image (core/narrowband.py's
    # docstring; ui/main_window.py's guard) -- stretch must precede it.
    assert "stretch" in s
    assert s.index("stretch") < s.index("narrowband")


def test_no_graxpert_still_produces_a_plan():
    # background/denoise fall back to built-ins; plan is never empty and never raises
    plan = build_auto_plan(_broadband_stack(), Settings(), data_type="broadband")
    s = _stages(plan)
    assert len(plan) >= 4
    assert "background" not in s      # no graxpert configured -> omitted, not faked


def test_graxpert_available_adds_background_stage(tmp_path):
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings, data_type="broadband")
    assert "background" in _stages(plan)


def test_denoise_engine_prefers_rcastro_over_graxpert(tmp_path):
    rcastro = tmp_path / "rcastro"
    rcastro.write_text("#!/bin/sh\n")
    rcastro.chmod(0o755)
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(rcastro_path=str(rcastro), graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings, data_type="broadband")
    noise_option = dict(plan)["noise_sharpen"]
    assert noise_option["engine"] == "rcastro"


def test_denoise_engine_falls_back_to_graxpert(tmp_path):
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings, data_type="broadband")
    noise_option = dict(plan)["noise_sharpen"]
    assert noise_option["engine"] == "graxpert"


def test_denoise_engine_none_when_nothing_installed():
    plan = build_auto_plan(_broadband_stack(), Settings(), data_type="broadband")
    noise_option = dict(plan)["noise_sharpen"]
    assert noise_option["engine"] is None


def test_data_type_defaults_to_detection_when_omitted():
    plan = build_auto_plan(_dualband_stack(), Settings())
    assert "narrowband" in _stages(plan)


def test_run_auto_plan_applies_each_step():
    base = _broadband_stack()
    plan = build_auto_plan(base, Settings(), data_type="broadband")
    out = run_auto_plan(base, plan, Settings())
    assert len(out) == len(plan)
    names = [n for n, _o, _img in out]
    assert "Stretch" in names or "Color" in names           # real steps ran
    # crop may legitimately shrink the frame; just confirm a real image came out
    assert out[-1][2].data.shape[0] <= base.data.shape[0]
    assert out[-1][2].data.shape[1] <= base.data.shape[1]

    # Each step's image threads forward: crop's output feeds color's input,
    # etc, and every step returns a real AstroImage.
    for _name, _option, img in out:
        assert img.data.size > 0


def test_run_auto_plan_reports_progress():
    base = _broadband_stack()
    plan = build_auto_plan(base, Settings(), data_type="broadband")
    calls = []
    run_auto_plan(base, plan, Settings(), on_progress=lambda i, n, name: calls.append((i, n, name)))
    assert len(calls) == len(plan)
    assert calls[0][1] == len(plan)


def test_run_auto_plan_skips_failing_step_and_continues():
    class _Boom:
        name = "Boom"
        def apply(self, img, option):
            raise RuntimeError("external tool exploded")

    import nocturne.core.auto_enhance as auto_enhance_mod

    base = _broadband_stack()
    plan = build_auto_plan(base, Settings(), data_type="broadband")
    real_make_step = auto_enhance_mod.make_step

    def _patched(stage_id, settings, *, bg_runner, rc_runner):
        if stage_id == "stretch":
            return _Boom()
        return real_make_step(stage_id, settings, bg_runner=bg_runner, rc_runner=rc_runner)

    auto_enhance_mod.make_step = _patched
    try:
        out = run_auto_plan(base, plan, Settings())
    finally:
        auto_enhance_mod.make_step = real_make_step

    names = [n for n, _o, _img in out]
    assert "Stretch" not in names              # failing step skipped, not recorded
    assert len(out) == len(plan) - 1           # rest of the chain still ran
