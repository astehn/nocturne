from seestar_processor.ui.pipeline import (
    core_stages, path_stages, next_enabled, prev_enabled, STEP_NAME, PROCESSING_ORDER,
)


def test_core_stages_shared_prefix():
    assert [s.id for s in core_stages()] == [
        "load", "destination", "crop", "background", "color", "stretch",
    ]


def test_external_path_stops_after_stretch_with_export():
    ids = [s.id for s in path_stages("external")]
    assert ids == [
        "load", "destination", "crop", "background", "color", "stretch",
        "export_external",
    ]


def test_in_app_path_has_cosmetic_then_export():
    ids = [s.id for s in path_stages("in_app")]
    assert ids == [
        "load", "destination", "crop", "background", "color", "stretch",
        "saturation", "noise_sharpen", "export",
    ]


def test_next_prev_enabled_on_stage_list():
    stages = path_stages("in_app")
    assert next_enabled(stages, 0) == 1
    assert next_enabled(stages, len(stages) - 1) == len(stages) - 1  # clamp
    assert prev_enabled(stages, 0) == 0  # clamp
    assert prev_enabled(stages, 3) == 2


def test_step_name_and_order():
    assert STEP_NAME["noise_sharpen"] == "Noise & Sharpen"
    assert PROCESSING_ORDER == [
        "crop", "background", "color", "stretch", "saturation", "noise_sharpen",
    ]
