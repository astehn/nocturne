from seestar_processor.ui.pipeline import (
    core_stages, path_stages, next_enabled, prev_enabled, STEP_NAME, PROCESSING_ORDER,
)


def test_core_stages_expected():
    assert [s.id for s in core_stages()] == [
        "load", "crop", "background", "color", "stretch",
    ]


def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "stretch", "levels",
        "saturation", "noise_sharpen", "local_contrast", "star_reduction", "export",
    ]


def test_next_prev_enabled_on_stage_list():
    stages = path_stages()
    assert next_enabled(stages, 0) == 1
    assert next_enabled(stages, len(stages) - 1) == len(stages) - 1  # clamp
    assert prev_enabled(stages, 0) == 0  # clamp
    assert prev_enabled(stages, 3) == 2


def test_step_name_and_order():
    assert STEP_NAME["noise_sharpen"] == "Noise & Sharpen"
    assert STEP_NAME["levels"] == "Levels"
    assert STEP_NAME["star_reduction"] == "Star Reduction"
    assert "crop" not in STEP_NAME
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "stretch", "levels", "saturation",
        "noise_sharpen", "local_contrast", "star_reduction",
    ]


def test_geometry_names():
    from seestar_processor.ui.pipeline import GEOMETRY_NAMES
    assert GEOMETRY_NAMES == ("Crop", "Rotate", "Flip H", "Flip V")


def test_remove_green_positioned_after_color():
    from seestar_processor.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["remove_green"] == "Remove Green"
    i = PROCESSING_ORDER.index("remove_green")
    assert PROCESSING_ORDER[i - 1] == "color"
