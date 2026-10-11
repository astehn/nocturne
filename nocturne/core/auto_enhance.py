from __future__ import annotations

from typing import NamedTuple

from ..recipe import LEVELS_AUTO, serialize_option
from ..settings import Settings, astap_valid, graxpert_valid, rcastro_valid
from ..steps.factory import make_step
from ..steps.noise_sharpen import FREE
from ..tools.base import run_cli
from .color import ColorSettings
from .crop import CropParams, detect_content_bounds
from .filter_type import detect_data_type
from .image import AstroImage
from .narrowband import GOLD_BLUE, palette_defaults


# ---- One-tap auto-enhance plan ---------------------------------------------
# `build_auto_plan` never applies anything; it only returns the ordered
# (stage_id, native_option) list a caller feeds to the existing step pipeline
# (see steps/factory.py::make_step). The values were tuned on five of his
# masters (M 45, M 31, NGC 281, IC 1396A, M 27 — Auto Enhance study 2026-10-11,
# .superpowers/sdd/2026-10-11-auto-enhance/study-report.md) against his own
# hand edits of the same files, and approved by eye as three presets.

AUTO_CROP_MARGIN = 0.02          # extra trim (fraction of each side) beyond the detected content rectangle, to clear soft/registration edges
AUTO_BACKGROUND_STRENGTH = "strong"  # GraXpert extraction strength; GraXpert stays for Background (~20-40 s) even though it never denoises here
AUTO_LEVELS = (0.0, 1.0, 1.0)    # build-time placeholder (identity black/gamma/white); overridden at apply time in run_auto_plan by LEVELS_AUTO, since a black-point only means something once the image has been stretched
AUTO_GREEN_FRINGE = 1.0          # full-strength green fringe removal, all three presets
AUTO_DENOISE_STRONG = "strong"   # fixed level -- the image-based noise proxy didn't discriminate real Seestar data, so denoise always runs at "strong" (the engine follows _auto_denoise_engine)

# Deconvolution, RC-Astro (BlurXTerminator) only: his hand edits of every study
# target used medium on broadband and strong on dual-band, at 6-13 s per image.
# The free unsharp-mask fallback is not what he does, so without RC-Astro the
# stage is left out rather than substituted.
AUTO_DECONVOLUTION = {"broadband": "medium", "dualband": "strong"}

# Natural. Stretch 0.30 = the manual default (STRETCH_DEFAULT).
AUTO_STRETCH_AMOUNT = 0.3
AUTO_SATURATION_AMOUNT = 0.5     # native saturation slider amount (0.5 = neutral)
AUTO_SATURATION_NEBULA = 0.2     # broadband nebula boost; M 31 / M 27 nebula sat 0.083 / 0.129 auto vs 0.111 / 0.115 by hand
# Dual-band nebula boost: at 0.2 IC 1396A's nebula saturation measured 0.531
# against 0.280 in his hand edit (study 2026-10-11) — LP data is already
# coloured by the filter, so it gets half the boost.
AUTO_SATURATION_NEBULA_DUALBAND = 0.1
AUTO_LOCAL_CONTRAST = 0.15       # light local-contrast finishing pass
# Star Reduction: he uses 0.24-0.5 by hand on every study target; leaving it
# out was the most visible difference between Auto Enhance and his edits.
AUTO_STAR_REDUCTION = 0.30

# Vivid: the study's weakest preset, approved. Saturation is capped at 0.6 —
# M 45's reflection nebula went green at 0.65 in the study sketch.
VIVID_STRETCH_AMOUNT = 0.40
VIVID_SATURATION = (0.6, 0.4)
VIVID_LOCAL_CONTRAST = 0.30
VIVID_STAR_REDUCTION = 0.45

# Gold and blue (dual-band only): Natural without Saturation / Local Contrast,
# then the gold-and-blue palette at its own shipped defaults. Good on NGC 281
# and IC 1396A; M 27 (small target, empty sky) went orange/blue mottled, which
# is why it is the user's pick and never automatic.
GOLD_BLUE_STAR_REDUCTION = 0.40

_ENGINE = object()      # table marker: the denoise engine chosen for this machine

# The presets: ONE table of stage lists, after the common head (Background,
# Color, Deconvolution — see build_auto_plan). A value that differs by data type
# is a {"broadband": ..., "dualband": ...} dict; "unknown" reads as broadband.
PRESETS: dict[str, tuple[tuple[str, object], ...]] = {
    "natural": (
        ("stretch", AUTO_STRETCH_AMOUNT),
        ("levels", AUTO_LEVELS),
        ("saturation", {"broadband": (AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA),
                        "dualband": (AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA_DUALBAND)}),
        ("green_fringe", AUTO_GREEN_FRINGE),
        ("noise_sharpen", _ENGINE),
        ("local_contrast", AUTO_LOCAL_CONTRAST),
        ("star_reduction", AUTO_STAR_REDUCTION),
    ),
    "vivid": (
        ("stretch", VIVID_STRETCH_AMOUNT),
        ("levels", AUTO_LEVELS),
        ("saturation", VIVID_SATURATION),
        ("green_fringe", AUTO_GREEN_FRINGE),
        ("noise_sharpen", _ENGINE),
        ("local_contrast", VIVID_LOCAL_CONTRAST),
        ("star_reduction", VIVID_STAR_REDUCTION),
    ),
    "gold_blue": (
        ("stretch", AUTO_STRETCH_AMOUNT),
        ("levels", AUTO_LEVELS),
        ("green_fringe", AUTO_GREEN_FRINGE),
        ("noise_sharpen", _ENGINE),
        # Before Narrowband, as the manual history has it: Narrowband is a
        # toolbar step appended after the processing stages.
        ("star_reduction", GOLD_BLUE_STAR_REDUCTION),
        ("narrowband", GOLD_BLUE),
    ),
}
DUALBAND_ONLY = frozenset({"gold_blue"})
# How each preset is written for a person: the menu, the busy label, the log.
PRESET_NAMES = {"natural": "Natural", "vivid": "Vivid", "gold_blue": "Gold and blue"}


def _auto_crop_option(img) -> CropParams:
    """Trim to the detected content rectangle plus a small extra margin
    (AUTO_CROP_MARGIN) to clear soft/registration edges. Degrades to a no-op
    crop if the measured rectangle is degenerate (e.g. a tiny/blank image)."""
    top, bottom, left, right = detect_content_bounds(img)
    h, w = bottom - top, right - left
    dh = min(int(h * AUTO_CROP_MARGIN), max(0, (h - 1) // 2))
    dw = min(int(w * AUTO_CROP_MARGIN), max(0, (w - 1) // 2))
    bounds = (top + dh, bottom - dh, left + dw, right - dw)
    if bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
        return CropParams()
    return CropParams(bounds=bounds)


def _auto_denoise_engine(settings: Settings) -> str:
    """Nocturne NR model > NoiseXTerminator > the built-in denoise — never
    GraXpert. A GraXpert denoise took 668 s of a 746 s Auto Enhance run on a
    20 MP master (study 2026-10-11), and a one-tap tool that sits for ten
    minutes reads as broken whatever the progress says; the built-in "strong"
    takes ~2 s. With both a model and RC-Astro, the Preferred denoise engine
    setting decides when it names one of them; otherwise the model first."""
    from . import nr_models
    models = nr_models.available()
    has_rc = rcastro_valid(settings)
    pref = getattr(settings, "denoise_engine", "")
    if models:
        ids = {m.id for m in models}
        if isinstance(pref, str) and pref.startswith(nr_models.PREFIX) \
                and pref[len(nr_models.PREFIX):] in ids:
            return pref
        if has_rc and pref == "rcastro":
            return "rcastro"
        # A model shipped with the app wins (as in nr_models), else the newest:
        # discover() lists in delivery order.
        pool = [m for m in models if m.shipped] or models
        return nr_models.PREFIX + pool[-1].id
    return "rcastro" if has_rc else FREE


def stages_left_out(settings: Settings) -> list[str]:
    """Head stages the plan leaves out for the tools installed, in plan order:
    Background without GraXpert, Deconvolution without RC-Astro."""
    out = []
    if not graxpert_valid(settings):
        out.append("background")
    if not rcastro_valid(settings):
        out.append("deconvolution")
    return out


def build_auto_plan(img, settings: Settings, include_crop: bool = True,
                    preset: str = "natural") -> list[tuple[str, object]]:
    """Build (do not apply) a preset's one-tap enhance plan: a list of
    (stage_id, native_option) pairs matching steps/factory.py's stage_ids and
    recipe.py::serialize_option's native option types for each stage.

    `preset` is a key of PRESETS. "gold_blue" raises ValueError unless the
    image's FILTER card says dual-band — a palette built from Ha/OIII means
    nothing on broadband data, and the UI never offers it there.

    When `include_crop` is False the auto-crop stage is omitted — used when the
    caller has already applied the user's own crop and Auto Enhance must respect
    it rather than re-detecting a border-trim crop of its own.

    Adaptive to the data type (Deconvolution strength, nebula boost) and to
    which external tools are installed: Background only with GraXpert,
    Deconvolution only with RC-Astro (see `stages_left_out`), photometric
    colour only with ASTAP (sky-neutralize otherwise; the Color step itself
    steps aside to sky balance on dual-band data). Left out of every preset:
    Recover Core and Curves, which are judgement calls on the picture."""
    if preset not in PRESETS:
        raise ValueError(f"unknown Auto Enhance preset {preset!r}")
    data_type = detect_data_type(getattr(img, "metadata", None) or {})
    if preset in DUALBAND_ONLY and data_type != "dualband":
        raise ValueError(f"the {preset!r} preset needs dual-band (LP filter) data")
    by_data = "dualband" if data_type == "dualband" else "broadband"

    plan: list[tuple[str, object]] = []
    if include_crop:
        plan.append(("crop", _auto_crop_option(img)))
    if graxpert_valid(settings):
        plan.append(("background", AUTO_BACKGROUND_STRENGTH))
    method = "photometric" if astap_valid(settings) else "sky"
    plan.append(("color", ColorSettings(method=method)))
    if rcastro_valid(settings):
        plan.append(("deconvolution", AUTO_DECONVOLUTION[by_data]))

    from ..steps.stretch_step import new_stretch_option
    for stage_id, value in PRESETS[preset]:
        if isinstance(value, dict):
            value = value[by_data]
        if stage_id == "stretch":
            # With its version, or the recorded step would replay as version 1.
            value = new_stretch_option(value)
        elif stage_id == "noise_sharpen":
            value = {"engine": _auto_denoise_engine(settings), "level": AUTO_DENOISE_STRONG}
        elif stage_id == "narrowband":
            value = palette_defaults(value)
        plan.append((stage_id, value))
    return plan


class AutoRun(NamedTuple):
    """What `run_auto_plan` did. `results` and `engines` are aligned: one entry
    per applied stage; `failures` names every stage that raised."""

    results: list[tuple[str, object, AstroImage]]   # (step.name, serialized option, image after)
    failures: list[tuple[str, str]]                 # (step.name, short reason)
    engines: list[str | None]                       # step.last_engine per result (None: no engine)
    # A step's own message for the person (Color's sky-balance fallback or its
    # dual-band step-aside): the steps are built here, so the caller cannot ask them.
    notes: tuple[str, ...] = ()


_REASON_MAX = 120


def _short_reason(exc: BaseException) -> str:
    """First line of the message, capped; the exception type when it has none."""
    text = str(exc).strip().splitlines()
    line = text[0].strip() if text else ""
    if not line:
        return type(exc).__name__
    return line if len(line) <= _REASON_MAX else line[:_REASON_MAX - 1].rstrip() + "\u2026"


def run_auto_plan(base, plan, settings: Settings, *, bg_runner=run_cli, rc_runner=run_cli,
                   on_progress=None) -> AutoRun:
    """Apply an auto-enhance plan (as built by build_auto_plan) in order,
    starting from `base` and threading the image forward through each stage.

    Mirrors batch.py::apply_recipe's engine wiring (make_step + step.apply on
    the *native* option -- never round-tripped through
    recipe.serialize_option/deserialize_option, which would e.g. silently
    turn crop into a no-op by dropping CropParams.bounds). Crop bounds are
    re-detected from the image actually reaching that stage (same
    conservative margin as _auto_crop_option), matching apply_recipe's
    per-image auto-detection instead of trusting a possibly-stale bounds
    computed when the plan was built.

    Returns an AutoRun. Its `results` hold (step.name, serialized_option,
    image_after_step) per successfully-applied step -- the display name and a
    serialize_option() encoding (fine for recording/display; only the apply
    above must use the native option) so the caller can fold each stage into
    the live Project's editable history via Project.record_precomputed without
    recomputing the slow external-tool steps.

    Robust to a single stage failing (e.g. an external tool subprocess
    errors): that stage is skipped -- not recorded, image left unchanged --
    and the rest of the chain still runs. It is no longer silent: each one is
    in `failures` as (step.name, short reason), for the caller to show.
    Cancelled is a BaseException and propagates; it is never a failure."""
    from .tasks import Cancelled, current

    img = base
    n = len(plan)
    results: list[tuple[str, object, AstroImage]] = []
    failures: list[tuple[str, str]] = []
    engines: list[str | None] = []
    notes: list[str] = []
    for i, (stage_id, option) in enumerate(plan):
        tok = current()
        if tok is not None and tok.cancelled:
            raise Cancelled()      # stop the chain cleanly between steps (a mid-step
                                   # subprocess is already killed via run_cli's token)
        step = make_step(stage_id, settings, bg_runner=bg_runner, rc_runner=rc_runner)
        try:
            if stage_id == "crop":
                option = _auto_crop_option(img)
            elif stage_id == "levels":
                # Was black-point-only here because auto_levels' adaptive gamma
                # lifted midtones and produced a milky look. That is fixed at
                # source (2026-08-20) — auto_levels now returns gamma and white
                # of 1.0 itself — so take it whole rather than keep a local
                # workaround that hides the real behaviour.
                # The DECISION, not this frame's measurement. `LevelsStep`
                # re-derives it, so the picture here is identical — but a
                # recipe saved after one tap now re-derives per image too,
                # instead of freezing a black point measured off whichever
                # frame happened to be open. The user never pressed Auto,
                # so nothing in the UI could have corrected it.
                option = LEVELS_AUTO
            result = step.apply(img, option)
        except Exception as exc:
            failures.append((step.name, _short_reason(exc)))
            if on_progress is not None:
                on_progress(i + 1, n, step.name)
            continue
        img = result
        recorded = getattr(step, "recorded_option", lambda o: o)(option)
        results.append((step.name, serialize_option(stage_id, recorded), img))
        engines.append(getattr(step, "last_engine", None))
        if getattr(step, "last_message", ""):
            notes.append(step.last_message)
        if on_progress is not None:
            on_progress(i + 1, n, step.name)
    return AutoRun(results, failures, engines, tuple(notes))
