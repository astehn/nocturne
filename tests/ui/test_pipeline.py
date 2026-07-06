from nocturne.ui.pipeline import (
    core_stages, path_stages, next_enabled, prev_enabled, STEP_NAME, PROCESSING_ORDER,
)


def test_core_stages_expected():
    assert [s.id for s in core_stages()] == [
        "load", "crop", "background", "color", "deconvolution", "stretch",
    ]


def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch", "levels",
        "saturation", "noise_sharpen", "local_contrast", "star_reduction", "enhancements",
        "export",
    ]


def test_next_prev_enabled_on_stage_list():
    stages = path_stages()
    assert next_enabled(stages, 0) == 1
    assert next_enabled(stages, len(stages) - 1) == len(stages) - 1  # clamp
    assert prev_enabled(stages, 0) == 0  # clamp
    assert prev_enabled(stages, 3) == 2


def test_step_name_and_order():
    assert STEP_NAME["noise_sharpen"] == "Noise Reduction"
    assert STEP_NAME["levels"] == "Levels"
    assert STEP_NAME["star_reduction"] == "Star Reduction"
    assert "crop" not in STEP_NAME
    assert PROCESSING_ORDER == [
        "background", "color", "remove_green", "deconvolution", "stretch", "levels",
        "saturation", "noise_sharpen", "local_contrast", "star_reduction",
    ]


def test_geometry_names():
    from nocturne.ui.pipeline import GEOMETRY_NAMES
    assert GEOMETRY_NAMES == ("Crop", "Rotate", "Flip H", "Flip V")


def test_remove_green_positioned_after_color():
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["remove_green"] == "Remove Green"
    i = PROCESSING_ORDER.index("remove_green")
    assert PROCESSING_ORDER[i - 1] == "color"


def test_deconvolution_stage_and_order():
    from nocturne.ui.pipeline import (
        PROCESSING_ORDER, STEP_NAME, path_stages)
    assert STEP_NAME["deconvolution"] == "Deconvolution"
    assert STEP_NAME["noise_sharpen"] == "Noise Reduction"
    i = PROCESSING_ORDER.index("deconvolution")
    assert PROCESSING_ORDER[i - 1] == "remove_green"
    assert PROCESSING_ORDER[i + 1] == "stretch"
    ids = [s.id for s in path_stages()]
    assert "deconvolution" in ids and ids.index("deconvolution") < ids.index("stretch")


def test_enhancements_stage_and_names():
    from nocturne.ui.pipeline import ENHANCE_NAMES, PROCESSING_ORDER, path_stages
    assert ENHANCE_NAMES == ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky")
    ids = [s.id for s in path_stages()]
    assert ids.index("star_reduction") < ids.index("enhancements") < ids.index("export")
    assert "enhancements" not in PROCESSING_ORDER   # append-only, not a truncating position


def test_post_stretch_ids_are_the_finishing_steps_minus_export():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, PROCESSING_ORDER
    assert POST_STRETCH_IDS == frozenset({
        "levels", "saturation", "noise_sharpen",
        "local_contrast", "star_reduction", "enhancements",
    })
    assert "export" not in POST_STRETCH_IDS
    assert "stretch" not in POST_STRETCH_IDS
    pre = PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
    assert POST_STRETCH_IDS.isdisjoint(pre)
