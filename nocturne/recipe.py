from __future__ import annotations

import json
from dataclasses import dataclass, field

from .core.color import ColorSettings
from .core.crop import CropParams
from .ui.pipeline import STEP_NAME, ENHANCE_NAMES

_NAME_TO_STAGE = {name: sid for sid, name in STEP_NAME.items()}
_NAME_TO_STAGE["Crop"] = "crop"  # geometry op — no longer in STEP_NAME but still recipe-serializable
_NAME_TO_STAGE["Rotate"] = "rotate"
_NAME_TO_STAGE["Flip H"] = "flip_h"
_NAME_TO_STAGE["Flip V"] = "flip_v"
_NAME_TO_STAGE["Narrowband"] = "narrowband"   # tool step, not a stepper stage
_NAME_TO_STAGE["Colour Balance"] = "color_balance"   # finishing tool, appends


@dataclass
class Recipe:
    steps: list = field(default_factory=list)


def serialize_option(stage_id, option):
    if stage_id == "crop":
        c = option if isinstance(option, CropParams) else CropParams()
        return {"aspect": c.aspect, "rotate": c.rotate, "flip_h": c.flip_h, "flip_v": c.flip_v}
    if stage_id == "color":
        c = option if isinstance(option, ColorSettings) else ColorSettings()
        # Explicit, not a dataclass dump — so a NEW FIELD MUST BE ADDED HERE or
        # it is silently dropped on save and the project reproduces differently.
        return {"neutralize_background": c.neutralize_background,
                "remove_green": c.remove_green,
                "method": c.method}
    if stage_id == "tint":
        t, w = option if option else (0.0, 0.0)
        return [float(t), float(w)]
    if stage_id == "levels":
        b, g, w = option if option else (0.0, 1.0, 1.0)
        return [b, g, w]
    if stage_id == "stretch":
        return float(option) if option not in (None, "") else 0.5
    if stage_id in ("local_contrast", "star_reduction", "recover_core", "green_fringe",
                    "remove_green"):
        try:
            return float(option)
        except (TypeError, ValueError):
            return option   # legacy string ("" from the old parameterless Remove Green)
    if stage_id == "curves":
        pts = option if option else [(0.0, 0.0), (1.0, 1.0)]
        return [[float(x), float(y)] for x, y in pts]
    if stage_id == "saturation":
        amount, nebula = option if isinstance(option, (tuple, list)) else (option, 0.0)
        return [float(amount), float(nebula)]
    if stage_id == "color_balance":
        o = option or {}
        def _triple(key):
            v = o.get(key) or (0.0, 0.0, 0.0)
            return [float(v[0]), float(v[1]), float(v[2])]
        return {"shadows": _triple("shadows"), "midtones": _triple("midtones"),
                "highlights": _triple("highlights"),
                "preserve_lum": bool(o.get("preserve_lum", True)),
                "strength": float(o.get("strength", 1.0)),
                # The band is stored as MEASURED, not re-derived on replay: a
                # preset is a starting point computed once from the image in
                # front of you, and a recipe that re-fitted it per image would
                # silently mean something different on every frame.
                "lo": float(o.get("lo", 0.0)),
                "hi": float(o.get("hi", 1.0)),
                "feather": float(o.get("feather", 0.08)),
                "invert": bool(o.get("invert", False))}
    if stage_id == "narrowband":
        from .core.narrowband import NarrowbandParams
        p = option if isinstance(option, NarrowbandParams) else NarrowbandParams()
        return {
            "palette": p.palette, "blackpoint": p.blackpoint, "oiii_boost": p.oiii_boost,
            "blend_amount": p.blend_amount, "highlight_reduction": p.highlight_reduction,
            "brightness": p.brightness, "highlight_recover": p.highlight_recover,
            "saturation": p.saturation, "lightness_preserve": p.lightness_preserve,
            "protect_background": p.protect_background, "scnr": p.scnr,
        }
    return option  # background / noise_sharpen: str


def deserialize_option(stage_id, value):
    if stage_id == "enhance":
        return value
    if stage_id == "crop":
        return CropParams(bounds=None, aspect=value["aspect"], rotate=value["rotate"],
                          flip_h=value["flip_h"], flip_v=value["flip_v"])
    if stage_id == "color":
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ColorSettings)}
        return ColorSettings(**{k: v for k, v in value.items() if k in fields})
    if stage_id == "tint":
        return tuple(value) if value else (0.0, 0.0)
    if stage_id == "levels":
        return tuple(value)
    if stage_id == "rotate":
        return CropParams(rotate=90)
    if stage_id == "flip_h":
        return CropParams(flip_h=True)
    if stage_id == "flip_v":
        return CropParams(flip_v=True)
    if stage_id == "curves":
        return [tuple(p) for p in value]
    if stage_id == "saturation":
        if isinstance(value, (tuple, list)):
            return (float(value[0]), float(value[1]))
        return (float(value), 0.0)   # legacy bare float
    if stage_id == "color_balance":
        def _triple(key):
            v = value.get(key) or (0.0, 0.0, 0.0)
            return [float(v[0]), float(v[1]), float(v[2])]
        out = {"shadows": _triple("shadows"), "midtones": _triple("midtones"),
               "highlights": _triple("highlights"),
               "preserve_lum": bool(value.get("preserve_lum", True)),
               "strength": float(value.get("strength", 1.0)),
               "lo": float(value.get("lo", 0.0)),
               "hi": float(value.get("hi", 1.0)),
               "feather": float(value.get("feather", 0.08)),
               "invert": bool(value.get("invert", False))}
        # Read the shape saved before each tonal range had its own amounts: one
        # `tone` plus a single triple. Projects written on this branch in the
        # last few hours have it, and must still open unchanged.
        if "tone" in value and value["tone"] in out:
            out[value["tone"]] = [float(value.get("red", 0.0)),
                                  float(value.get("green", 0.0)),
                                  float(value.get("blue", 0.0))]
        return out
    if stage_id == "narrowband":
        import dataclasses
        from .core.narrowband import NarrowbandParams
        fields = {f.name for f in dataclasses.fields(NarrowbandParams)}
        return NarrowbandParams(**{k: v for k, v in value.items() if k in fields})
    return value


def recipe_from_entries(entries) -> Recipe:
    steps = []
    for name, option in entries:
        if name in ENHANCE_NAMES:
            steps.append({"stage": "enhance", "option": name})
            continue
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
        if (_NAME_TO_STAGE.get(name) is None and name not in ENHANCE_NAMES
                and name not in seen):
            seen.append(name)
    return seen


def missing_tools(recipe: Recipe, settings) -> list[str]:
    """External tools this recipe CANNOT run without and that are not configured
    on this machine. Sits next to uncaptured_step_names because it answers the
    same shape of question about a recipe: what will not happen if you use it.

    Today that is GraXpert alone. steps/factory builds every other tool-backed
    stage (saturation, noise_sharpen, star_reduction, deconvolution,
    green_fringe, narrowband) with `rc=None` when RC-Astro is absent, and each
    falls back to a free implementation, so those recipes run fine. `background`
    is built with a GraXpert unconditionally, so step.apply raises — and
    run_batch's per-file `except` then loses the WHOLE file rather than the one
    step, identically for every file in the folder, under an errno message that
    never mentions GraXpert.

    Deliberately NOT a check on what would merely improve the result. A recipe
    that runs without RC-Astro must not be blocked because RC-Astro would have
    done it better, or the gate stops being a fact and becomes an opinion.
    """
    from .settings import graxpert_valid
    needs_gx = any(step.get("stage") == "background" and step.get("option") != "off"
                   for step in recipe.steps)
    return ["GraXpert"] if needs_gx and not graxpert_valid(settings) else []


@dataclass(frozen=True)
class StepPlan:
    """What one step of a recipe will actually do, before anything runs."""

    step: str        # the name the user sees
    outcome: str     # "run" | "substitute" | "fail"
    engine: str      # what will do it ("" when it will fail)
    reason: str      # why, when it is not simply going to run

    @property
    def ok(self) -> bool:
        return self.outcome != "fail"


def preflight(recipe: Recipe, settings) -> list[StepPlan]:
    """Step by step: what will run, what will be substituted, what will fail.

    `missing_tools` already answers "can this recipe run at all", and the batch
    dialog blocks on it. This is the other half — the positive statement. A
    recipe that CAN run may still not do what its author did: six of the eight
    tool-backed stages silently fall back to a free implementation, and until
    now nothing said so before a folder of files was processed with it.

    Pure, and it reuses `core.receipt` so the answer here and the engine named
    in a provenance report cannot disagree.
    """
    from .core.receipt import engine_for
    from .ui.pipeline import STEP_NAME

    blocked = set(missing_tools(recipe, settings))
    plans: list[StepPlan] = []
    for step in recipe.steps:
        sid = step.get("stage")
        name = (str(step.get("option")) if sid == "enhance"
                else STEP_NAME.get(sid, sid or "?"))
        # The OPTION can make the engine irrelevant: Background "off" returns
        # the image untouched and never reaches GraXpert, which is why
        # missing_tools excludes it. A preflight that ignored the option would
        # report a failure that cannot happen, and the two answers about the
        # same recipe would contradict each other.
        if sid == "background" and step.get("option") == "off":
            plans.append(StepPlan(name, "run", "", ""))
            continue
        note = engine_for(sid, settings)
        if note is None:                       # no engine choice: it just runs
            plans.append(StepPlan(name, "run", "", ""))
        elif note.unavailable:
            plans.append(StepPlan(name, "fail", "", note.reason))
        elif note.is_fallback:
            plans.append(StepPlan(name, "substitute", note.engine, note.reason))
        else:
            plans.append(StepPlan(name, "run", note.engine, ""))
    # A blocked tool must show as a failure even if the stage-level check above
    # thought otherwise — the two are computed differently and the stricter one
    # wins, or the preflight would promise a run the batch then aborts.
    if blocked:
        plans = [p if p.outcome != "run" or not _needs_blocked(p, blocked) else
                 StepPlan(p.step, "fail", "", f"{', '.join(sorted(blocked))} is not configured")
                 for p in plans]
    return plans


def _needs_blocked(plan: StepPlan, blocked: set) -> bool:
    return any(tool.lower() in (plan.engine or "").lower() for tool in blocked)


def preflight_summary(plans) -> str:
    """One line for a status bar: what a user needs to know before pressing Run."""
    fails = [p for p in plans if p.outcome == "fail"]
    subs = [p for p in plans if p.outcome == "substitute"]
    if fails:
        return f"{len(fails)} step{'s' if len(fails) > 1 else ''} cannot run: " \
               + "; ".join(f"{p.step} — {p.reason}" for p in fails)
    if subs:
        return f"{len(subs)} step{'s' if len(subs) > 1 else ''} will use a built-in " \
               f"substitute: " + ", ".join(f"{p.step} ({p.engine})" for p in subs)
    n = len(plans)
    return ("This step will run as saved." if n == 1
            else f"All {n} steps will run as saved.")


def save_recipe(recipe: Recipe, path: str) -> None:
    with open(path, "w") as f:
        json.dump({"version": 1, "steps": recipe.steps}, f, indent=2)


def load_recipe(path: str) -> Recipe:
    with open(path) as f:
        data = json.load(f)
    return Recipe(steps=data.get("steps", []))
