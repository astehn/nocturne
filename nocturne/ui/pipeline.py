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
]

_IN_APP_TAIL = [
    Stage("recover_core", "Recover Core", "recover_core"),
    Stage("levels", "Levels", "levels"),
    Stage("curves", "Curves", "curves"),
    Stage("saturation", "Saturation", "saturation"),
    Stage("green_fringe", "Remove Green Fringe", "green_fringe"),
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
    "remove_green": "Remove Green",
    "deconvolution": "Deconvolution",
    "ai_denoise": "AI Denoise",
    "stretch": "Stretch",
    "recover_core": "Recover Core",
    "levels": "Levels",
    "curves": "Curves",
    "saturation": "Saturation",
    "green_fringe": "Remove Green Fringe",
    "noise_sharpen": "Noise Reduction",
    "local_contrast": "Local Contrast",
    "star_reduction": "Star Reduction",
}
PROCESSING_ORDER = [
    "background", "color", "tint", "remove_green", "deconvolution", "stretch",
    "recover_core", "levels", "curves", "saturation", "green_fringe",
    "noise_sharpen", "local_contrast", "star_reduction",
]
# "Trim" is a late, finishing crop appended AFTER processing (see trim_dialog).
# It belongs here because these names are what "the framing changed" means: a
# trim must invalidate a plate solve exactly as a crop does. It is deliberately
# NOT named "Crop" so the provenance report can tell the two apart, and so
# _has_crop keeps meaning "the user cropped before processing".
GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V", "Trim")
ENHANCE_NAMES = ("Boost Red", "Boost Cyan", "Boost Blue", "Darken Sky", "Lighten Sky",
                 "Vibrance", "Star Colour", "Soft Glow", "Boost Gold", "Dark Structure")

# Finishing steps that operate in display space and require a stretched image.
# These are the in-app tail stages minus "export" (exporting a linear file is
# legitimate, so Export never forces a stretch).
POST_STRETCH_IDS = frozenset({
    "recover_core", "levels", "curves", "saturation", "green_fringe", "noise_sharpen",
    "local_contrast", "star_reduction", "enhancements",
})


def core_stages() -> list[Stage]:
    return list(_CORE)


def path_stages() -> list[Stage]:
    return list(_CORE) + list(_IN_APP_TAIL)


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
