from __future__ import annotations

from .core.curves import normalize_curves

import json
from dataclasses import dataclass, field

from .core.color import ColorSettings
from .core.crop import CropParams
from .ui.pipeline import STEP_NAME, ENHANCE_NAMES

_NAME_TO_STAGE = {name: sid for sid, name in STEP_NAME.items()}
from .core.levels import AUTO as LEVELS_AUTO   # re-exported: the one definition
from . import RELEASE_STAGE, __version__

_NAME_TO_STAGE["Crop"] = "crop"  # geometry op — no longer in STEP_NAME but still recipe-serializable
_NAME_TO_STAGE["Rotate"] = "rotate"
_NAME_TO_STAGE["Flip H"] = "flip_h"
_NAME_TO_STAGE["Flip V"] = "flip_v"
_NAME_TO_STAGE["Narrowband"] = "narrowband"   # tool step, not a stepper stage

# A recipe saved before 2026-09-09 carries `oiii_boost`, which both matched the
# channels and chose the look. There is no honest mapping onto the two controls
# that replaced it, and deserialize_option filters to KNOWN field names — so
# without the check in preflight() the value would vanish silently and the step
# would render with a default it was never given. Beta software: refuse, and say
# which step and why.
LEGACY_OIII_REASON = ("saved before the oxygen controls changed — "
                      "open it in Narrowband and re-save the recipe")
_NAME_TO_STAGE["Colour Balance"] = "color_balance"   # finishing tool, appends
# Pre-rename display names (see history/project_store._RENAMED_STEPS). A
# cached step from an old bundle is translated to its new name on load, but
# _stage_for must still resolve the old name too — belt-and-suspenders for an
# old-named entry that somehow reaches save_project without going through
# load_project first (e.g. a partially-migrated in-memory project).
_NAME_TO_STAGE["Remove Green"] = "remove_green"        # now "De-green Sky"
_NAME_TO_STAGE["Remove Green Fringe"] = "green_fringe"  # now "De-green Stars"
# Starless Levels is deliberately ABSENT. Its two numbers come from a person
# looking at one picture — that is the whole premise of the tool — so replaying
# them across a folder of different targets would mean something different on
# every frame. Being absent here is what makes uncaptured_step_names report it,
# so Save Recipe warns honestly instead of promising a step it cannot replay.


# Stages Nocturne no longer has, by the id a recipe saved them under, with the
# name the user knew them by. A recipe that carries one still runs: the step is
# skipped (batch.apply_recipe) and the preflight says so — once, in plain words.
# Deliberately absent from _NAME_TO_STAGE, so a new recipe cannot contain one
# and Save Recipe reports a legacy entry as a step it cannot include.
RETIRED_STAGES = {"ai_denoise": "Linear Denoise"}   # retired 2026-10-05


def retired_reason(stage_id) -> str:
    return f"{RETIRED_STAGES[stage_id]} is no longer part of Nocturne — skipped"


@dataclass
class Recipe:
    steps: list = field(default_factory=list)


# Stages whose live option is a settings object. A reopened project restores
# cached steps with the option as SAVED (a dict), and the branches below read a
# dict as "not my type" and wrote the defaults: Save Recipe after reopening turned
# Narrowband into default HOO, a rotated 16:9 crop into Original, photometric
# colour into sky (since July; found 2026-10-09). Read the dict back first.
_OBJECT_OPTIONS = ("crop", "color", "narrowband")


def serialize_option(stage_id, option):
    if stage_id in _OBJECT_OPTIONS and isinstance(option, dict):
        option = _from_saved_dict(stage_id, option)
    if stage_id == "crop":
        c = option if isinstance(option, CropParams) else CropParams()
        return {"aspect": c.aspect, "rotate": c.rotate, "flip_h": c.flip_h, "flip_v": c.flip_v}
    if stage_id == "color":
        c = option if isinstance(option, ColorSettings) else ColorSettings()
        # Explicit, not a dataclass dump — so a NEW FIELD MUST BE ADDED HERE or
        # it is silently dropped on save and the project reproduces differently.
        out = {"neutralize_background": c.neutralize_background,
               "remove_green": c.remove_green,
               "method": c.method}
        if c.fell_back:
            # Only when true: files without a fallback stay byte-identical,
            # and files written before the field read it as False.
            out["fell_back"] = True
        return out
    if stage_id == "tint":
        t, w = option if option else (0.0, 0.0)
        return [float(t), float(w)]
    if stage_id == "levels":
        # "auto" is the DECISION, not a measurement: the black point came from
        # `auto_levels` on one image's noise floor, and replaying that number on
        # another frame applies the wrong floor to it. Stored as a string beside
        # the existing list, so type alone tells them apart and every recipe
        # saved before this still means exactly what it did.
        if option == LEVELS_AUTO:
            return LEVELS_AUTO
        b, g, w = option if option else (0.0, 1.0, 1.0)
        return [b, g, w]
    if stage_id == "stretch":
        # The dict is what the visual picker produces; a bare float is every
        # recipe saved before 2026-09-14. Serialize to the dict either way, so
        # the stored shape is ONE thing rather than two that drift.
        from .steps.stretch_step import parse_stretch_linked, parse_stretch_option
        return {"amount": parse_stretch_option(option),
                "linked": parse_stretch_linked(option)}
    if stage_id in ("local_contrast", "star_reduction", "recover_core", "green_fringe",
                    "remove_green"):
        try:
            return float(option)
        except (TypeError, ValueError):
            return option   # legacy string ("" from the old parameterless De-green Sky)
    if stage_id == "curves":
        # The option is a MATRIX (channel/target -> points) since the large
        # editor arrived on 2026-09-05; this still read it as one list of
        # points, so Save Recipe raised and a project bundle kept the dict
        # unconverted. normalize_curves accepts every shape it has ever had.
        return {k: [[float(x), float(y)] for x, y in pts]
                for k, pts in normalize_curves(option).items()}
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
            "palette": p.palette, "blackpoint": p.blackpoint,
            "oxygen_strength": p.oxygen_strength,
            "blend_amount": p.blend_amount, "highlight_reduction": p.highlight_reduction,
            "brightness": p.brightness, "highlight_recover": p.highlight_recover,
            "saturation": p.saturation, "lightness_preserve": p.lightness_preserve,
            "protect_background": p.protect_background, "scnr": p.scnr,
            "gold_strength": p.gold_strength, "blue_strength": p.blue_strength,
        }
    return option  # background / noise_sharpen: str


def _from_saved_dict(stage_id, value: dict):
    """The settings object for an option stored as a dict."""
    return deserialize_option(stage_id, value)


def deserialize_option(stage_id, value):
    if stage_id == "enhance":
        return value
    if stage_id == "crop":
        # Lenient: a recipe or bundle written before a field existed reads it
        # as the default rather than failing.
        return CropParams(bounds=None, aspect=value.get("aspect", "Original"),
                          rotate=value.get("rotate", 0), flip_h=value.get("flip_h", False),
                          flip_v=value.get("flip_v", False))
    if stage_id == "color":
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ColorSettings)}
        return ColorSettings(**{k: v for k, v in value.items() if k in fields})
    if stage_id == "tint":
        return tuple(value) if value else (0.0, 0.0)
    if stage_id == "levels":
        return LEVELS_AUTO if value == LEVELS_AUTO else tuple(value)
    if stage_id == "rotate":
        return CropParams(rotate=90)
    if stage_id == "flip_h":
        return CropParams(flip_h=True)
    if stage_id == "flip_v":
        return CropParams(flip_v=True)
    if stage_id == "curves":
        # A dict (the matrix) or, from before 2026-09-05, a bare list meaning
        # the RGB curve. Reading the matrix as a list turned its keys into
        # tuples of characters, and every project with Curves failed to reopen
        # ("too many values to unpack") — found 2026-10-05.
        return normalize_curves(value)
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
        # One reading of a stored option, shared with the step: a partial dict
        # takes its palette's own defaults, not HOO's.
        from .steps.narrowband_step import parse_narrowband_option
        return parse_narrowband_option(value)
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
    outcome: str     # "run" | "substitute" | "fail" | "skip" (a retired step)
    engine: str      # what will do it ("" when it will fail)
    reason: str      # why, when it is not simply going to run

    @property
    def ok(self) -> bool:
        return self.outcome != "fail"


def _step_display_name(stage_id) -> str:
    """The name the user knows a step by.

    STEP_NAME only covers the STEPPER stages, so every tool and geometry step —
    Narrowband, Colour Balance, Crop, Rotate, Flip — fell through to its raw
    stage id and a preflight said "flip_h" or "color_balance" at the user.
    _NAME_TO_STAGE already holds those names; this reads it backwards.
    """
    from .ui.pipeline import STEP_NAME

    if not stage_id:
        return "?"
    if stage_id in STEP_NAME:
        return STEP_NAME[stage_id]
    for name, sid in _NAME_TO_STAGE.items():
        if sid == stage_id:
            return name
    return stage_id



CANNOT_BUILD_REASON = ("this version of Nocturne cannot replay that step — "
                       "open the image and apply it by hand, or re-save the recipe")


def _can_build(stage_id, settings) -> bool:
    """Whether `make_step` can construct this stage at all.

    Geometry ops and the enhancement taps never reach `make_step` on replay, so
    they are answered directly rather than being refused for not being there.
    """
    if not stage_id or stage_id in ("enhance",):
        return True
    from .steps.factory import make_step
    try:
        make_step(stage_id, settings)
    except ValueError:
        return False
    except Exception:
        # Anything else is an environment problem (a missing binary, say), which
        # `engine_for` reports far better than a bare "cannot build" would.
        return True
    return True


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
                else _step_display_name(sid))
        opt = step.get("option")
        if sid in RETIRED_STAGES:
            plans.append(StepPlan(RETIRED_STAGES[sid], "skip", "", retired_reason(sid)))
            continue
        if sid == "narrowband" and isinstance(opt, dict) and "oiii_boost" in opt:
            plans.append(StepPlan(name, "fail", "", LEGACY_OIII_REASON))
            continue
        # The OPTION can make the engine irrelevant: Background "off" returns
        # the image untouched and never reaches GraXpert, which is why
        # missing_tools excludes it. A preflight that ignored the option would
        # report a failure that cannot happen, and the two answers about the
        # same recipe would contradict each other.
        if sid == "background" and step.get("option") == "off":
            plans.append(StepPlan(name, "run", "", ""))
            continue
        # Can the factory actually BUILD this stage? Nothing asked before, so a
        # stage that was registered as capturable but had no `make_step` case
        # was reported as "will run as saved" and then raised on replay —
        # `run_batch` catching that per file turned it into a failure for every
        # file in the folder, with a raw stage id as the message. Colour Balance
        # was in exactly that state. Answering the question this function claims
        # to answer costs one construction per step, before any file is touched.
        if not _can_build(sid, settings):
            plans.append(StepPlan(name, "fail", "", CANNOT_BUILD_REASON))
            continue
        if sid == "noise_sharpen" and isinstance(opt, dict):
            nr_plan = _nr_plan(name, opt.get("engine"))
            if nr_plan is not None:
                plans.append(nr_plan)
                continue
        note = engine_for(sid, settings,
                          opt.get("engine") if sid == "noise_sharpen"
                          and isinstance(opt, dict) else None)
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


def _nr_plan(name: str, engine) -> StepPlan | None:
    """A Nocturne NR model runs or fails — it has no substitute, so the
    settings-based `engine_for` (which would say NoiseXTerminator) is not asked."""
    from .core import nr_models
    if not (isinstance(engine, str) and engine.startswith(nr_models.PREFIX)):
        return None
    model_id = engine[len(nr_models.PREFIX):]
    if nr_models.find(model_id) is None:
        return StepPlan(name, "fail", "", nr_models.not_installed(model_id))
    if not nr_models.runtime_available():
        return StepPlan(name, "fail", "", "Nocturne NR needs onnxruntime, which this "
                                          "build does not include")
    return StepPlan(name, "run", nr_models.engine_label(model_id), "")


def _needs_blocked(plan: StepPlan, blocked: set) -> bool:
    return any(tool.lower() in (plan.engine or "").lower() for tool in blocked)


def preflight_summary(plans) -> str:
    """One line for a status bar: what a user needs to know before pressing Run.

    A skipped (retired) step is said first and ONCE however often the recipe
    names it, then the rest is summarised as if it were not there — it is not
    a step that will run, so "All 3 steps will run" would count it as one."""
    notes = list(dict.fromkeys(p.reason for p in plans if p.outcome == "skip"))
    rest = [p for p in plans if p.outcome != "skip"]
    if not notes:
        return _summary(plans)
    return ". ".join(notes) + "." + (" " + _summary(rest) if rest else "")


def _summary(plans) -> str:
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


class RecipeVersionError(ValueError):
    """A recipe written by a different pre-1.0 build of Nocturne."""


def save_recipe(recipe: Recipe, path: str) -> None:
    # `app` is the Nocturne that wrote it; `version` is the FILE SCHEMA and is
    # a different thing. See load_recipe for why the app version is recorded.
    with open(path, "w") as f:
        json.dump({"version": 1, "app": __version__, "steps": recipe.steps},
                  f, indent=2)


def load_recipe(path: str) -> Recipe:
    """Read a recipe, refusing one written by a different pre-1.0 build.

    Andreas, 2026-09-14, having watched replay compatibility cost something on
    nearly every change: *"quite a lot of effort goes into fixing recipes when
    we do changes... i could probably argue for that we should remove that
    functionality entirely"* until 1.0.

    The diagnosis was right and deletion was the wrong cure — Batch dies with
    recipes, and it would not even fix the problem, because Saved Projects
    replay too. This is the cheap version of the same goal: stop PROTECTING
    compatibility instead of removing the feature. A step's meaning can then
    change freely while the pipeline is still being settled, and a recipe from
    an older build says so out loud rather than quietly producing a different
    picture.

    Gated on RELEASE_STAGE, so the strictness lifts itself at 1.0 rather than
    needing someone to remember. A recipe with no `app` field predates this and
    is refused for the same reason: it was written by an unknown older build.
    """
    with open(path) as f:
        data = json.load(f)
    if RELEASE_STAGE:
        wrote = data.get("app")
        if wrote != __version__:
            raise RecipeVersionError(
                f"This recipe was saved by Nocturne "
                f"{wrote or 'an earlier version'}, and you are running "
                f"{__version__}. While Nocturne is in {RELEASE_STAGE}, steps "
                f"still change shape between versions, so replaying it could "
                f"quietly give you a different picture. Open an image, apply "
                f"the steps you want and save the recipe again."
            )
    return Recipe(steps=data.get("steps", []))
