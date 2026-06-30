from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    kind: str  # "load" | "process" | "stretch" | "export" | "placeholder"
    enabled: bool


PIPELINE: list[Stage] = [
    Stage("load", "Load", "load", True),
    Stage("crop", "Crop", "crop", True),
    Stage("background", "Background", "process", True),
    Stage("color", "Color", "color", True),
    Stage("deconvolution", "Deconvolution", "process", True),
    Stage("noise", "Noise", "process", True),
    Stage("stretch", "Stretch", "stretch", True),
    Stage("final_fixes", "Final Fixes", "final_fixes", True),
    Stage("stars", "Starless / Stars", "placeholder", False),
    Stage("export", "Export", "export", True),
]

STEP_NAME = {
    "crop": "Crop",
    "background": "Background",
    "color": "Color",
    "deconvolution": "Deconvolution",
    "noise": "Noise",
    "stretch": "Stretch",
    "final_fixes": "Final Fixes",
}
PROCESSING_ORDER = [
    "crop", "background", "color", "deconvolution", "noise", "stretch", "final_fixes",
]


def next_enabled(index: int) -> int:
    for i in range(index + 1, len(PIPELINE)):
        if PIPELINE[i].enabled:
            return i
    return index


def prev_enabled(index: int) -> int:
    for i in range(index - 1, -1, -1):
        if PIPELINE[i].enabled:
            return i
    return index
