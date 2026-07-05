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
    Stage("stretch", "Stretch", "stretch"),
]

_IN_APP_TAIL = [
    Stage("levels", "Levels", "levels"),
    Stage("saturation", "Saturation", "saturation"),
    Stage("noise_sharpen", "Noise Reduction", "process"),
    Stage("local_contrast", "Local Contrast", "process"),
    Stage("star_reduction", "Star Reduction", "process"),
    Stage("export", "Export", "export"),
]

STEP_NAME = {
    "background": "Background",
    "color": "Color",
    "remove_green": "Remove Green",
    "deconvolution": "Deconvolution",
    "stretch": "Stretch",
    "levels": "Levels",
    "saturation": "Saturation",
    "noise_sharpen": "Noise Reduction",
    "local_contrast": "Local Contrast",
    "star_reduction": "Star Reduction",
}
PROCESSING_ORDER = [
    "background", "color", "remove_green", "deconvolution", "stretch", "levels",
    "saturation", "noise_sharpen", "local_contrast", "star_reduction",
]
GEOMETRY_NAMES = ("Crop", "Rotate", "Flip H", "Flip V")


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
