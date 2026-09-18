from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    kind: str
    enabled: bool = True


# Shared core (linear).
_CORE = [
    Stage("load", "Import", "import"),
    Stage("crop", "Crop", "crop"),
    Stage("background", "Background", "process"),
    Stage("color", "Color", "auto"),
    Stage("deconvolution", "Deconvolution", "process"),
    # AI Denoise is BUILT but deliberately NOT SHIPPED. The only trained model,
    # denoise_s30_v1, over-corrects deep stacks — it damaged the 405-frame M8
    # master by +19.1%, and 250-450 frames is precisely what users bring. The
    # step stays in STEP_NAME and steps/factory so a saved project that already
    # names it still resolves; only its place in the visible pipeline is gone.
    # Restore this Stage and its PROCESSING_ORDER entry when a model passes the
    # deep-end gate. See docs/superpowers/specs/2026-08-24-n2n-v2-postmortem.md.
    Stage("stretch", "Stretch", "stretch"),
    # Was a button on the Color panel, five steps before its own cause: the
    # green cast this fixes is CREATED by the stretch (Bayer gives green
    # twice the photosites, so neutral_stretch amplifies it ~1.9x). Moved
    # here, right after Stretch, so the panel's own advice ("reach for this
    # only if a cast survives the stretch") is something the user can
    # actually judge. See docs/superpowers/specs for the move's rationale.
    Stage("remove_green", "De-green Sky", "remove_green"),
]

_IN_APP_TAIL = [
    Stage("recover_core", "Recover Core", "recover_core"),
    Stage("levels", "Levels", "levels"),
    Stage("curves", "Curves", "curves"),
    Stage("saturation", "Saturation", "saturation"),
    Stage("green_fringe", "De-green Stars", "green_fringe"),
    Stage("noise_sharpen", "Noise Reduction", "process"),
    Stage("local_contrast", "Local Contrast", "local_contrast"),
    Stage("star_reduction", "Star Reduction", "star_reduction"),
    Stage("enhancements", "Enhancements", "enhance"),
    Stage("export", "Export", "export"),
]

STEP_NAME = {
    "background": "Background",
    "color": "Color",
    "tint": "Colour Tint",
    "remove_green": "De-green Sky",
    "deconvolution": "Deconvolution",
    "ai_denoise": "AI Denoise",
    "stretch": "Stretch",
    "recover_core": "Recover Core",
    "levels": "Levels",
    "curves": "Curves",
    "saturation": "Saturation",
    "green_fringe": "De-green Stars",
    "noise_sharpen": "Noise Reduction",
    "local_contrast": "Local Contrast",
    "star_reduction": "Star Reduction",
}
PROCESSING_ORDER = [
    # `ai_denoise` sits between deconvolution and stretch because that is where
    # its stage appears when one is offered (see _OPTIONAL). It is listed even
    # though the stage is normally absent: this order answers "what came before
    # this step", and a saved project or an internal test run that contains an
    # AI Denoise entry has to place it correctly. A missing id raises ValueError
    # from .index() — which is exactly how it announced itself.
    "background", "color", "tint", "deconvolution", "ai_denoise", "stretch", "remove_green",
    "recover_core", "levels", "curves", "saturation", "green_fringe",
    "noise_sharpen", "local_contrast", "star_reduction",
]
# "Trim" is a late, finishing crop appended AFTER processing (see trim_dialog).
# It belongs here because these names are what "the framing changed" means: a
# trim must invalidate a plate solve exactly as a crop does. It is deliberately
# NOT named "Crop" so the provenance report can tell the two apart, and so
# _has_crop keeps meaning "the user cropped before processing".
GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V", "Trim")
# Every enhancement the Enhancements panel offers. This tuple decides what a
# recipe can serialise (recipe.py) and what counts as an enhancement in the
# history (main_window.py), so a tap missing from it is dropped from recipes AND
# reported as un-capturable — a shipped, supported action treated as
# unsupported. "Sharpen Nebulosity" was missing exactly that way; there is a
# test asserting this list matches the buttons the panel actually builds.
ENHANCE_NAMES = ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky",
                 "Vibrance", "Star Colour", "Soft Glow", "Boost Gold", "Dark Structure",
                 "Sharpen Nebulosity")

# Steps that operate in display space and require a stretched image: the
# in-app tail stages minus "export" (exporting a linear file is legitimate,
# so Export never forces a stretch), plus "remove_green" — a _CORE stage, but
# one whose whole premise ("the stretch already neutralises the sky") only
# holds once the stretch has actually run.
POST_STRETCH_IDS = frozenset({
    "remove_green",
    "recover_core", "levels", "curves", "saturation", "green_fringe", "noise_sharpen",
    "local_contrast", "star_reduction", "enhancements",
})


def core_stages() -> list[Stage]:
    return list(_CORE)


# Stages that are NOT part of the pipeline and must be asked for by id.
#
# `ai_denoise` is out of _CORE deliberately and stays out — the only trained
# model over-corrected deep stacks and damaged a 405-frame M 8 by 19%, which is
# pinned by test_ai_denoise_is_built_but_not_shipped. It is offered ONLY when a
# model from the separate Nocturne NR project is sitting in ~/.nocturne/models,
# which no release build can contain.
#
# Opt-IN rather than default-plus-omit, so the guard above keeps its meaning:
# `path_stages()` with no arguments is still the shipped pipeline, and anything
# extra has to be named by a caller that knows why.
_OPTIONAL = {
    # id -> (stage, the id it is inserted BEFORE)
    "ai_denoise": (Stage("ai_denoise", "AI Denoise", "process"), "stretch"),
}


def path_stages(omit: frozenset[str] = frozenset(),
                include: frozenset[str] = frozenset()) -> list[Stage]:
    """The visible pipeline, minus any ids in `omit`, plus any in `include`.

    Filtered rather than flag-mutated because `Stage` is frozen and `_CORE` is
    module level: every caller is handed the SAME objects, so mutating one would
    poison every later project in the session.

    An included stage lands at a FIXED position — AI Denoise before Stretch,
    because that is where the model was trained and the only place it can work.
    A stretch derives its curve from the image's own statistics, so afterwards
    the noise has been shaped by a transfer function the model never saw, and
    the single sigma value it is conditioned on no longer describes the frame.
    """
    stages = [s for s in list(_CORE) + list(_IN_APP_TAIL) if s.id not in omit]
    for sid in include:
        stage, before = _OPTIONAL[sid]
        if stage.id in {s.id for s in stages}:
            continue
        at = next((i for i, s in enumerate(stages) if s.id == before), len(stages))
        stages.insert(at, stage)
    return stages


def next_enabled(stages: list[Stage], index: int) -> int:
    for i in range(index + 1, len(stages)):
        if stages[i].enabled:
            return i
    return index


def prev_enabled(stages: list[Stage], index: int) -> int:
    for i in range(index - 1, -1, -1):
        if stages[i].enabled:
            return i
    return index
