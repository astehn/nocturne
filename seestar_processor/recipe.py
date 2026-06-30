from __future__ import annotations

import json
from dataclasses import dataclass, field

from .core.color import ColorSettings
from .core.crop import CropParams
from .ui.pipeline import STEP_NAME

_NAME_TO_STAGE = {name: sid for sid, name in STEP_NAME.items()}


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
                "white_balance": c.white_balance, "remove_green": c.remove_green}
    if stage_id == "levels":
        b, g, w = option if option else (0.0, 1.0, 1.0)
        return [b, g, w]
    if stage_id == "stretch":
        return float(option) if option not in (None, "") else 0.5
    return option  # background / noise_sharpen / local_contrast / star_reduction: str


def deserialize_option(stage_id, value):
    if stage_id == "crop":
        return CropParams(bounds=None, aspect=value["aspect"], rotate=value["rotate"],
                          flip_h=value["flip_h"], flip_v=value["flip_v"])
    if stage_id == "color":
        return ColorSettings(**value)
    if stage_id == "levels":
        return tuple(value)
    return value


def recipe_from_entries(entries) -> Recipe:
    steps = []
    for name, option in entries:
        sid = _NAME_TO_STAGE.get(name)
        if sid is None:
            continue
        steps.append({"stage": sid, "option": serialize_option(sid, option)})
    return Recipe(steps=steps)


def save_recipe(recipe: Recipe, path: str) -> None:
    with open(path, "w") as f:
        json.dump({"version": 1, "steps": recipe.steps}, f, indent=2)


def load_recipe(path: str) -> Recipe:
    with open(path) as f:
        data = json.load(f)
    return Recipe(steps=data.get("steps", []))
