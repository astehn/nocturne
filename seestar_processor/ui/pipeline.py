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
    Stage("color", "Color", "placeholder", False),
    Stage("deconvolution", "Deconvolution", "placeholder", False),
    Stage("noise", "Noise", "placeholder", False),
    Stage("stretch", "Stretch", "stretch", True),
    Stage("final_fixes", "Final Fixes", "placeholder", False),
    Stage("export", "Export", "export", True),
]

STEP_NAME = {"crop": "Crop", "background": "Background", "stretch": "Stretch"}
PROCESSING_ORDER = ["crop", "background", "stretch"]


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
