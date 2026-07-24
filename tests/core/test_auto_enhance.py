import numpy as np

from nocturne.core.auto_enhance import AUTO_LEVELS, build_auto_plan, detect_data_type, run_auto_plan
from nocturne.core.image import AstroImage
from nocturne.settings import Settings
from nocturne.ui.pipeline import PROCESSING_ORDER


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
    # detect_data_type is still exercised (FILTER capture) even though
    # build_auto_plan no longer branches on it.
    assert detect_data_type({"filter": "LP"}) == "dualband"
    assert detect_data_type({"filter": "lp"}) == "dualband"       # case-insensitive


def test_other_filter_is_broadband():
    assert detect_data_type({"filter": "IRCUT"}) == "broadband"
    assert detect_data_type({"filter": "UV/IR"}) == "broadband"


def test_absent_filter_is_unknown():
    assert detect_data_type({}) == "unknown"
    assert detect_data_type({"filter": ""}) == "unknown"


def test_plan_shape_without_graxpert():
    img = _broadband_stack()
    plan = build_auto_plan(img, Settings())
    s = _stages(plan)
    assert s == ["crop", "color", "stretch", "levels", "saturation",
                 "green_fringe", "noise_sharpen", "local_contrast"]
    # aggressive/removed steps excluded
    assert "narrowband" not in s
    assert "deconvolution" not in s and "star_reduction" not in s
    assert "curves" not in s and "recover_core" not in s


def test_plan_shape_with_graxpert(tmp_path):
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings)
    s = _stages(plan)
    assert s == ["crop", "background", "color", "stretch", "levels", "saturation",
                 "green_fringe", "noise_sharpen", "local_contrast"]


def test_plan_uses_photometric_color_when_astap_available(tmp_path):
    astap = tmp_path / "astap"
    astap.write_text("#!/bin/sh\n")
    astap.chmod(0o755)
    settings = Settings(astap_path=str(astap))
    plan = build_auto_plan(_broadband_stack(), settings)
    options = dict(plan)
    assert options["color"].method == "photometric"


def test_plan_uses_sky_color_without_astap():
    plan = build_auto_plan(_broadband_stack(), Settings())
    options = dict(plan)
    assert options["color"].method == "sky"


def test_plan_uses_photometric_color_for_dualband_data_too(tmp_path):
    # The dual-band/narrowband branch is gone -- LP-filter data goes through
    # the exact same photometric-color path as everything else.
    astap = tmp_path / "astap"
    astap.write_text("#!/bin/sh\n")
    astap.chmod(0o755)
    settings = Settings(astap_path=str(astap))
    plan = build_auto_plan(_dualband_stack(), settings)
    options = dict(plan)
    assert options["color"].method == "photometric"
    assert "narrowband" not in _stages(plan)


def test_no_graxpert_still_produces_a_plan():
    # background/denoise fall back to built-ins; plan is never empty and never raises
    plan = build_auto_plan(_broadband_stack(), Settings())
    s = _stages(plan)
    assert len(plan) >= 4
    assert "background" not in s      # no graxpert configured -> omitted, not faked


def test_graxpert_available_adds_background_stage(tmp_path):
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings)
    s = _stages(plan)
    assert "background" in s
    assert s.index("background") == s.index("crop") + 1


def test_denoise_engine_prefers_rcastro_over_graxpert(tmp_path):
    rcastro = tmp_path / "rcastro"
    rcastro.write_text("#!/bin/sh\n")
    rcastro.chmod(0o755)
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(rcastro_path=str(rcastro), graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings)
    noise_option = dict(plan)["noise_sharpen"]
    assert noise_option["engine"] == "rcastro"


def test_denoise_engine_falls_back_to_graxpert(tmp_path):
    graxpert = tmp_path / "graxpert"
    graxpert.write_text("#!/bin/sh\n")
    graxpert.chmod(0o755)
    settings = Settings(graxpert_path=str(graxpert))
    plan = build_auto_plan(_broadband_stack(), settings)
    noise_option = dict(plan)["noise_sharpen"]
    assert noise_option["engine"] == "graxpert"


def test_denoise_engine_none_when_nothing_installed():
    plan = build_auto_plan(_broadband_stack(), Settings())
    noise_option = dict(plan)["noise_sharpen"]
    assert noise_option["engine"] is None


def test_denoise_level_is_always_strong():
    # Real Seestar data measured too low/uniform for the old MAD-based proxy
    # to discriminate -- denoise is now fixed at "strong" regardless of what
    # tools (if any) are installed.
    plan = build_auto_plan(_broadband_stack(), Settings())
    assert dict(plan)["noise_sharpen"]["level"] == "strong"


def test_plan_stage_ids_are_a_monotonic_prefix_of_processing_order():
    # The re-edit machinery requires the recorded plan's PROCESSING_ORDER
    # stages to appear in strictly-increasing PROCESSING_ORDER index order.
    for settings in (Settings(),):
        plan = build_auto_plan(_broadband_stack(), settings)
        indices = [PROCESSING_ORDER.index(sid) for sid in _stages(plan) if sid in PROCESSING_ORDER]
        assert indices == sorted(indices)
        assert len(indices) == len(set(indices))


def test_run_auto_plan_applies_each_step():
    base = _broadband_stack()
    plan = build_auto_plan(base, Settings())
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

    recorded_ids = [sid for sid, _ in plan]
    assert "narrowband" not in recorded_ids
    assert "deconvolution" not in recorded_ids
    assert "star_reduction" not in recorded_ids


def test_run_auto_plan_records_flat_gamma_levels():
    # AUTO_LEVELS in the built plan is just an identity placeholder -- once
    # the plan reaches the (post-stretch) image at apply time, run_auto_plan
    # must recompute a real auto_levels() black-point but keep gamma/white
    # flat (1.0), since auto_levels()'s adaptive gamma (~1.37) lifts
    # midtones and produced the milky look the user rejected.
    base = _broadband_stack()
    plan = build_auto_plan(base, Settings())
    assert dict(plan)["levels"] == AUTO_LEVELS   # build-time placeholder is still identity

    out = run_auto_plan(base, plan, Settings())
    levels_entries = [(name, opt) for name, opt, _img in out if name == "Levels"]
    assert len(levels_entries) == 1
    _name, recorded = levels_entries[0]
    black, gamma, white = recorded
    assert black > 0.0
    assert gamma == 1.0
    assert white == 1.0


def test_run_auto_plan_reports_progress():
    base = _broadband_stack()
    plan = build_auto_plan(base, Settings())
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
    plan = build_auto_plan(base, Settings())
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


def test_run_auto_plan_stops_on_cancel():
    import pytest
    from nocturne.core.tasks import CancelToken, Cancelled, set_ambient, clear_ambient
    img = _broadband_stack()
    plan = build_auto_plan(img, Settings())
    tok = CancelToken()
    tok.cancel()
    set_ambient(tok)                           # ambient token, cancelled
    try:
        with pytest.raises(Cancelled):         # chain bails (does not swallow-and-continue)
            run_auto_plan(img, plan, Settings())
    finally:
        clear_ambient()
