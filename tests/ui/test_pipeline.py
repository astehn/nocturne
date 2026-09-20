from nocturne.ui.pipeline import (
    core_stages, path_stages, next_enabled, prev_enabled, STEP_NAME, PROCESSING_ORDER,
)


def test_core_stages_expected():
    assert [s.id for s in core_stages()] == [
        "load", "crop", "background", "color", "deconvolution", "stretch", "remove_green",
    ]


def test_path_stages_single_linear_flow():
    ids = [s.id for s in path_stages()]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution", "stretch", "remove_green",
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
    # ai_denoise is LISTED here while its stage stays out of the shipped
    # pipeline (test_ai_denoise_is_built_but_not_shipped). This list answers
    # "what came before this step" for a history entry, and an internally
    # tested or saved Linear Denoise entry has to place correctly — a missing id
    # raises ValueError from .index().
    assert PROCESSING_ORDER == [
        "ai_denoise", "background", "color", "tint", "deconvolution", "stretch",
        "remove_green",
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


def test_remove_green_positioned_after_stretch():
    """The whole point of the move: De-green Sky (SCNR) fixes a green cast
    that the STRETCH creates (a Bayer sensor gives green twice the
    photosites, so neutral_stretch amplifies it ~1.9x — see stretch_invented_
    green in the training notes). Judging whether a cast survives the stretch
    is meaningless before the stretch has run, so the step must sit AFTER it
    — it used to sit five steps before, as a button on the Color panel.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["remove_green"] == "De-green Sky"
    assert PROCESSING_ORDER.index("remove_green") > PROCESSING_ORDER.index("stretch")
    # Still after Color too — de-greening operates on the calibrated result.
    assert PROCESSING_ORDER.index("remove_green") > PROCESSING_ORDER.index("color")


def test_colour_tint_runs_after_calibration():
    """calibrate -> nudge. The order Andreas asked for, pinned.

    Tint must come AFTER colour so it nudges a calibrated image rather than
    being undone by the calibration. It no longer has any ordering
    relationship to enforce against remove_green — that step moved off the
    Color panel entirely, onto its own stage after Stretch.
    """
    from nocturne.ui.pipeline import PROCESSING_ORDER, STEP_NAME
    assert STEP_NAME["tint"] == "Colour Tint"
    assert PROCESSING_ORDER.index("color") < PROCESSING_ORDER.index("tint")


def test_deconvolution_stage_and_order():
    from nocturne.ui.pipeline import (
        PROCESSING_ORDER, STEP_NAME, path_stages)
    assert STEP_NAME["deconvolution"] == "Deconvolution"
    assert STEP_NAME["noise_sharpen"] == "Noise Reduction"
    i = PROCESSING_ORDER.index("deconvolution")
    assert PROCESSING_ORDER[i - 1] == "tint"
    # What this test is really about: deconvolution is LINEAR work, before the
    # stretch. The assertion is the relationship, not the adjacency.
    assert PROCESSING_ORDER.index("deconvolution") < PROCESSING_ORDER.index("stretch")
    ids = [s.id for s in path_stages()]
    assert "deconvolution" in ids and ids.index("deconvolution") < ids.index("stretch")


def test_enhancements_stage_and_names():
    from nocturne.ui.pipeline import ENHANCE_NAMES, PROCESSING_ORDER, path_stages
    # Eleven, matching the buttons the Enhancements panel builds. It was ten:
    # "Sharpen Nebulosity" shipped in the panel but was never registered, so a
    # recipe dropped it and told the user it could not be captured — a
    # supported action treated as unsupported.
    assert ENHANCE_NAMES == ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky",
                             "Vibrance", "Star Colour", "Soft Glow", "Boost Gold", "Dark Structure",
                             "Sharpen Nebulosity")
    ids = [s.id for s in path_stages()]
    assert ids.index("star_reduction") < ids.index("enhancements") < ids.index("export")


def test_enhance_names_disjoint_from_step_and_geometry_names():
    """_truncation_target("enhancements") (main_window.py) walks the history
    backwards checking membership in ENHANCE_NAMES to decide where the run of
    taps started. That walk is only correct because no tap shares a name with
    a real step or a geometry op — a future tap named like one would make
    Reset on Enhancements silently eat that step's commit instead of stopping
    there."""
    from nocturne.ui.pipeline import ENHANCE_NAMES, GEOMETRY_NAMES, STEP_NAME
    assert set(ENHANCE_NAMES).isdisjoint(STEP_NAME.values())
    assert set(ENHANCE_NAMES).isdisjoint(GEOMETRY_NAMES)
    assert "enhancements" not in PROCESSING_ORDER   # append-only, not a truncating position


def test_post_stretch_ids_are_the_finishing_steps_minus_export():
    from nocturne.ui.pipeline import POST_STRETCH_IDS, PROCESSING_ORDER
    assert POST_STRETCH_IDS == frozenset({
        "remove_green",
        "recover_core", "levels", "curves", "saturation", "green_fringe", "noise_sharpen",
        "local_contrast", "star_reduction", "enhancements",
    })
    assert "export" not in POST_STRETCH_IDS
    assert "stretch" not in POST_STRETCH_IDS
    pre = PROCESSING_ORDER[: PROCESSING_ORDER.index("stretch")]
    assert POST_STRETCH_IDS.isdisjoint(pre)


def test_remove_green_requires_a_stretched_image():
    """remove_green is a _CORE stage, not part of _IN_APP_TAIL, but it still
    needs POST_STRETCH_IDS: its whole premise ("the stretch already
    neutralises the sky") only holds once the stretch has actually run, so
    arriving here on a still-linear image must force one — exactly like the
    in-app tail stages do. Without this a user who jumps straight to this
    step (skipping Stretch) would de-green a linear image instead."""
    from nocturne.ui.pipeline import POST_STRETCH_IDS
    assert "remove_green" in POST_STRETCH_IDS


def test_recover_core_placed_after_stretch():
    """Not immediately after any more — De-green Sky now sits between them,
    right after Stretch (see test_remove_green_positioned_after_stretch)."""
    from nocturne.ui.pipeline import POST_STRETCH_IDS, STEP_NAME
    ids = [s.id for s in path_stages()]
    assert ids.index("recover_core") == ids.index("remove_green") + 1
    assert ids.index("recover_core") > ids.index("stretch")
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
    assert STEP_NAME["green_fringe"] == "De-green Stars"
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
    # It IS in PROCESSING_ORDER since 2026-09-18, which does not weaken this
    # guard: that list is "what came before what", and a history entry naming
    # Linear Denoise has to place correctly whether or not the stage is offered.
    # The guard that matters is the two lines above — the stage is absent from
    # the pipeline unless a caller asks for it by id, which only happens when a
    # Nocturne NR model is sitting in ~/.nocturne/models.
    assert "ai_denoise" in PROCESSING_ORDER
    assert PROCESSING_ORDER.index("ai_denoise") < PROCESSING_ORDER.index("stretch"), \
        "the model runs on linear data; after the stretch it cannot"
    # Renamed to "Linear Denoise" on 2026-09-20 (see project_store._RENAMED_STEPS
    # for why). The name is what a RECIPE stores — recipe.py builds its lookup
    # from STEP_NAME — so what has to hold is not the string but that BOTH names
    # still resolve to this stage. Asserting the display string was the old
    # guard, and it would have passed a rename that silently orphaned every
    # recipe carrying the step.
    assert STEP_NAME["ai_denoise"] == "Linear Denoise"
    from nocturne.recipe import _NAME_TO_STAGE
    assert _NAME_TO_STAGE["Linear Denoise"] == "ai_denoise"
    assert _NAME_TO_STAGE["AI Denoise"] == "ai_denoise", \
        "a recipe saved before the rename must still replay"
    from nocturne.steps.factory import make_step
    from nocturne.settings import Settings
    assert make_step("ai_denoise", Settings()) is not None, "factory must still build it"
