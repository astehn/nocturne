from __future__ import annotations

import json
from dataclasses import dataclass, field

from .core.color import ColorSettings
from .core.crop import CropParams
from .ui.pipeline import STEP_NAME

_NAME_TO_STAGE = {name: sid for sid, name in STEP_NAME.items()}
_NAME_TO_STAGE["Crop"] = "crop"  # geometry op — no longer in STEP_NAME but still recipe-serializable
_NAME_TO_STAGE["Rotate"] = "rotate"
_NAME_TO_STAGE["Flip H"] = "flip_h"
_NAME_TO_STAGE["Flip V"] = "flip_v"


@dataclass
class Recipe:
    steps: list = field(default_factory=list)


def serialize_option(stage_id, option):
    if stage_id == "crop":
        c = option if isinstance(option, CropParams) else CropParams()
        return {"aspect": c.aspect, "rotate": c.rotate, "flip_h": c.flip_h, "flip_v": c.flip_v}
    if stage_id == "color":
        c = option if isinstance(option, ColorSettings) else ColorSettings()
        return {"neutralize_background": c.neutralize_background,
                "remove_green": c.remove_green}
    if stage_id == "levels":
        b, g, w = option if option else (0.0, 1.0, 1.0)
        return [b, g, w]
    if stage_id == "stretch":
        return float(option) if option not in (None, "") else 0.5
    if stage_id in ("local_contrast", "star_reduction", "recover_core"):
        try:
            return float(option)
        except (TypeError, ValueError):
            return option   # legacy string
    return option  # background / noise_sharpen: str


def deserialize_option(stage_id, value):
    if stage_id == "crop":
        return CropParams(bounds=None, aspect=value["aspect"], rotate=value["rotate"],
                          flip_h=value["flip_h"], flip_v=value["flip_v"])
    if stage_id == "color":
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ColorSettings)}
        return ColorSettings(**{k: v for k, v in value.items() if k in fields})
    if stage_id == "levels":
        return tuple(value)
    if stage_id == "rotate":
        return CropParams(rotate=90)
    if stage_id == "flip_h":
        return CropParams(flip_h=True)
    if stage_id == "flip_v":
        return CropParams(flip_v=True)
    return value


def recipe_from_entries(entries) -> Recipe:
    steps = []
    for name, option in entries:
        sid = _NAME_TO_STAGE.get(name)
        if sid is None:
            continue
        steps.append({"stage": sid, "option": serialize_option(sid, option)})
    return Recipe(steps=steps)


def uncaptured_step_names(entries) -> list[str]:
    """Distinct applied-step names a recipe can't serialize yet (e.g. the
    Enhancements taps), in first-seen order. Empty when everything the
    user applied is representable in a recipe."""
    seen: list[str] = []
    for name, _ in entries:
        if _NAME_TO_STAGE.get(name) is None and name not in seen:
            seen.append(name)
    return seen


def save_recipe(recipe: Recipe, path: str) -> None:
    with open(path, "w") as f:
        json.dump({"version": 1, "steps": recipe.steps}, f, indent=2)


def load_recipe(path: str) -> Recipe:
    with open(path) as f:
        data = json.load(f)
    return Recipe(steps=data.get("steps", []))
