from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    kind: str
    enabled: bool = True
    reason: str = ""      # why a listed stage is disabled — the step list's tooltip


# Shared core (linear).
_CORE = [
    Stage("load", "Import", "import"),
    Stage("crop", "Crop", "crop"),
    Stage("background", "Background", "process"),
    Stage("color", "Color", "auto"),
    Stage("deconvolution", "Deconvolution", "process"),
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
    "background", "color", "tint", "deconvolution", "stretch", "remove_green",
    "recover_core", "levels", "curves", "saturation", "green_fringe",
    "noise_sharpen", "local_contrast", "star_reduction",
]
# "Trim" is a late, finishing crop appended AFTER processing (see trim_dialog).
# It belongs here because these names are what "the framing changed" means: a
# trim must invalidate a plate solve exactly as a crop does. It is deliberately
# NOT named "Crop" so the provenance report can tell the two apart, and so
# _has_crop keeps meaning "the user cropped before processing".
GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V", "Trim")
# Steps Nocturne no longer has, which an OLD project's history can still hold —
# restored from their cached pixels like any cached step. Linear Denoise ran on
# the linear stack straight after Crop, ahead of everything in PROCESSING_ORDER,
# and was retired on 2026-10-05 with the whole pre-stretch track. It must still
# count as preceding every step: `_leading_kept` stops at the first name it does
# not recognise, so without this, re-applying Stretch on such a project would
# silently discard the entry and every step after it.
RETIRED_NAMES = ("Linear Denoise",)
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


def names_before(step_id: str) -> set[str]:
    """History names that precede `step_id`: what an Apply of it keeps, and the
    state its preview is drawn from. One answer for every caller."""
    return set(GEOMETRY_NAMES) | set(RETIRED_NAMES) | {
        STEP_NAME[sid] for sid in PROCESSING_ORDER[: PROCESSING_ORDER.index(step_id)]}


def path_stages(omit: frozenset[str] = frozenset(),
                disable: dict[str, str] | None = None) -> list[Stage]:
    """The visible pipeline, minus any ids in `omit`.

    Filtered rather than flag-mutated because `Stage` is frozen and `_CORE` is
    module level: every caller is handed the SAME objects, so mutating one would
    poison every later project in the session.

    `disable` keeps a stage LISTED but not enterable, with a reason. Omitting a
    stage the user can make available mid-session moved every row below it.
    """
    stages = [s for s in list(_CORE) + list(_IN_APP_TAIL) if s.id not in omit]
    if disable:
        stages = [replace(s, enabled=False, reason=disable[s.id]) if s.id in disable else s
                  for s in stages]
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
