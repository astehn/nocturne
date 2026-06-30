from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    kind: str
    enabled: bool = True


# Shared core (linear), run for both destinations.
_CORE = [
    Stage("load", "Import", "import"),
    Stage("destination", "Destination", "destination"),
    Stage("crop", "Crop", "crop"),
    Stage("background", "Background", "process"),
    Stage("color", "Color", "auto"),
    Stage("stretch", "Stretch", "stretch"),
]

_EXTERNAL_TAIL = [Stage("export_external", "Export", "export_external")]
_IN_APP_TAIL = [
    Stage("saturation", "Saturation", "saturation"),
    Stage("noise_sharpen", "Noise & Sharpen", "process"),
    Stage("export", "Export", "export"),
]

STEP_NAME = {
    "crop": "Crop",
    "background": "Background",
    "color": "Color",
    "stretch": "Stretch",
    "saturation": "Saturation",
    "noise_sharpen": "Noise & Sharpen",
}
PROCESSING_ORDER = [
    "crop", "background", "color", "stretch", "saturation", "noise_sharpen",
]


def core_stages() -> list[Stage]:
    return list(_CORE)


def path_stages(destination: str) -> list[Stage]:
    tail = _EXTERNAL_TAIL if destination == "external" else _IN_APP_TAIL
    return list(_CORE) + list(tail)


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
