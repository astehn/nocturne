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
        "load", "crop", "background", "color", "deconvolution", "stretch",
        "recover_core", "levels", "curves", "saturation", "green_fringe",
        "noise_sharpen", "local_contrast", "star_reduction", "enhancements", "export",
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
        "background", "color", "tint", "remove_green", "deconvolution",
        "stretch",
        "recover_core", "levels", "curves", "saturation", "green_fringe",
        "noise_sharpen", "local_contrast", "star_reduction",
    ]


def test_geometry_names():
    """These names are what "the framing changed" means: any of them invalidates
    a plate solve. "Trim" is the late, finishing crop (see trim_dialog) and
    belongs here for exactly that reason — deliberately not called "Crop", so
    _has_crop keeps meaning "cropped BEFORE processing"."""
    from nocturne.ui.pipeline import GEOMETRY_NAMES
    assert GEOMETRY_NAMES == ("Crop", "Rotate", "Flip H", "Flip V", "Trim")


def test_remove_green_positioned_after_color():
    """Intent preserved: Remove Green runs AFTER the colour calibration.

    It is no longer adjacent — Colour Tint sits between them, so the order is
    calibrate, nudge to taste, then de-green imported data. Asserting the
    RELATIVE order rather than adjacency keeps the requirement and stops the
    test breaking every time something is inserted nearby.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["remove_green"] == "Remove Green"
    assert PROCESSING_ORDER.index("remove_green") > PROCESSING_ORDER.index("color")


def test_colour_tint_runs_between_calibration_and_remove_green():
    """calibrate -> nudge -> de-green. The order Andreas asked for, pinned.

    Tint must come AFTER colour so it nudges a calibrated image rather than
    being undone by the calibration, and BEFORE remove_green so a de-green
    applies to the final colour.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["tint"] == "Colour Tint"
    assert (PROCESSING_ORDER.index("color")
            < PROCESSING_ORDER.index("tint")
            < PROCESSING_ORDER.index("remove_green"))


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
    assert ENHANCE_NAMES == ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky",
                             "Vibrance", "Star Colour", "Soft Glow", "Boost Gold", "Dark Structure")
    ids = [s.id for s in path_stages()]
    assert ids.index("star_reduction") < ids.index("enhancements") < ids.index("export")
    assert "enhancements" not in PROCESSING_ORDER   # append-only, not a truncating position


def test_post_stretch_ids_are_the_finishing_steps_minus_export():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, PROCESSING_ORDER
    assert POST_STRETCH_IDS == frozenset({
        "recover_core", "levels", "curves", "saturation", "green_fringe", "noise_sharpen",
        "local_contrast", "star_reduction", "enhancements",
    })
    assert "export" not in POST_STRETCH_IDS
    assert "stretch" not in POST_STRETCH_IDS
    pre = PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
    assert POST_STRETCH_IDS.isdisjoint(pre)


def test_recover_core_placed_after_stretch():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("recover_core") == ids.index("stretch") + 1
    assert ids.index("recover_core") < ids.index("levels")
    assert STEP_NAME["recover_core"] == "Recover Core"
    assert "recover_core" in POST_STRETCH_IDS


def test_curves_placed_after_levels():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("curves") == ids.index("levels") + 1
    assert ids.index("curves") < ids.index("saturation")
    assert STEP_NAME["curves"] == "Curves"
    assert "curves" in POST_STRETCH_IDS


def test_green_fringe_placed_after_saturation():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("green_fringe") == ids.index("saturation") + 1
    assert ids.index("green_fringe") < ids.index("noise_sharpen")
    assert STEP_NAME["green_fringe"] == "Remove Green Fringe"
    assert "green_fringe" in POST_STRETCH_IDS


def test_ai_denoise_is_built_but_not_shipped():
    """Deliberate absence, pinned so it cannot drift back in unnoticed.

    The step and its model exist; the only trained model (denoise_s30_v1)
    over-corrects deep stacks and damaged the 405-frame M8 master by +19.1%,
    and 250-450 frames is what users actually bring. It stays out of the
    visible pipeline until a model passes the deep-end gate.

    STEP_NAME and steps/factory KEEP their entries on purpose: a saved project
    that already names ai_denoise must still resolve rather than blow up.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME, core_stages, path_stages
    assert "ai_denoise" not in [s.id for s in core_stages()]
    assert "ai_denoise" not in [s.id for s in path_stages()]
    assert "ai_denoise" not in PROCESSING_ORDER
    assert STEP_NAME["ai_denoise"] == "AI Denoise", "keep the name for old projects"
    from nocturne.steps.factory import make_step
    from nocturne.settings import Settings
    assert make_step("ai_denoise", Settings()) is not None, "factory must still build it"
