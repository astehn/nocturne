from __future__ import annotations

from ..recipe import serialize_option
from ..settings import Settings, astap_valid, graxpert_valid, rcastro_valid
from ..steps.factory import make_step
from ..tools.base import run_cli
from .color import ColorSettings
from .crop import CropParams, detect_content_bounds
from .image import AstroImage
from .levels import auto_levels


def detect_data_type(metadata: dict) -> str:
    """'dualband' if the Seestar LP (Ha/OIII) filter, 'broadband' if a known
    other filter, 'unknown' if absent (caller should ask)."""
    filt = str(metadata.get("filter") or "").strip().upper()
    if not filt:
        return "unknown"
    return "dualband" if "LP" in filt else "broadband"


# ---- One-tap auto-enhance plan ---------------------------------------------
# All numeric/string defaults below are provisional — tuned on real data (see
# plan Final) — chosen as reasonable middle-of-road values for a balanced,
# non-aggressive finish. `build_auto_plan` never applies anything; it only
# returns the ordered (stage_id, native_option) list a caller feeds to the
# existing step pipeline (see steps/factory.py::make_step).

AUTO_CROP_MARGIN = 0.02          # provisional — tuned on real data (see plan Final): extra trim (fraction of each side) beyond the detected content rectangle, to clear soft/registration edges
AUTO_BACKGROUND_STRENGTH = "strong"  # provisional — tuned on real data (see plan Final): GraXpert extraction strength
AUTO_STRETCH_AMOUNT = 0.3        # provisional — tuned on real data (see plan Final): gentler stretch aggressiveness (see core/stretch.py amount_to_target)
AUTO_LEVELS = (0.0, 1.0, 1.0)    # build-time placeholder (identity black/gamma/white); overridden at apply time in run_auto_plan by auto_levels() on the stretched image, since a black-point only means something once the image has been stretched
AUTO_SATURATION_AMOUNT = 0.5     # provisional — tuned on real data (see plan Final): native saturation slider amount (0.5 = neutral)
AUTO_SATURATION_NEBULA = 0.2     # provisional — tuned on real data (see plan Final): light starless nebula-boost
AUTO_GREEN_FRINGE = 1.0          # provisional — tuned on real data (see plan Final): full-strength green fringe removal
AUTO_LOCAL_CONTRAST = 0.15       # provisional — tuned on real data (see plan Final): light local-contrast finishing pass

AUTO_DENOISE_STRONG = "strong"   # fixed level -- the image-based noise proxy didn't discriminate real Seestar data, so denoise always runs at "strong" (engine still adapts to what's installed)


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


def _auto_denoise_option(settings: Settings) -> dict:
    """Engine picked by availability (RC-Astro NoiseXTerminator first, else
    GraXpert, else the built-in TV fallback baked into NoiseSharpenStep when
    engine is None); level is always "strong" -- an earlier image-based noise
    proxy was measured to not discriminate real Seestar data (linear MAD
    ~0.00008, far below any sensible threshold, so it always picked "light" --
    too weak -- and post-stretch measures didn't separate noisy from clean
    either), so adaptivity was dropped in favor of a fixed strong level."""
    if rcastro_valid(settings):
        engine = "rcastro"
    elif graxpert_valid(settings):
        engine = "graxpert"
    else:
        engine = None
    return {"engine": engine, "level": AUTO_DENOISE_STRONG}


def build_auto_plan(img, settings: Settings, include_crop: bool = True) -> list[tuple[str, object]]:
    """Build (do not apply) the ordered one-tap enhance plan: a list of
    (stage_id, native_option) pairs matching steps/factory.py's stage_ids and
    recipe.py::serialize_option's native option types for each stage.

    When `include_crop` is False the auto-crop stage is omitted — used when the
    caller has already applied the user's own crop and Auto Enhance must respect
    it rather than re-detecting a border-trim crop of its own.

    Adaptive to the image (crop bounds) and to which external tools are
    installed (settings.*_valid). Never raises, even with a bare
    Settings() (nothing installed) -- background is simply omitted and
    denoise/color degrade to built-in engines. Always uses photometric colour
    (falling back to sky-neutralize when ASTAP isn't configured) for all
    data -- there is no separate dual-band/narrowband branch; narrowband
    (HOO) remains available only as a manual toolbar tool. Deliberately
    excludes the more aggressive stages (deconvolution, star_reduction,
    recover_core, curves) for a balanced, natural default; local_contrast
    and green_fringe are included as safe finishing steps."""
    plan: list[tuple[str, object]] = []
    if include_crop:
        plan.append(("crop", _auto_crop_option(img)))

    if graxpert_valid(settings):
        plan.append(("background", AUTO_BACKGROUND_STRENGTH))

    method = "photometric" if astap_valid(settings) else "sky"
    plan.append(("color", ColorSettings(method=method)))
    plan.append(("stretch", AUTO_STRETCH_AMOUNT))
    plan.append(("levels", AUTO_LEVELS))
    plan.append(("saturation", (AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA)))
    plan.append(("green_fringe", AUTO_GREEN_FRINGE))
    plan.append(("noise_sharpen", _auto_denoise_option(settings)))
    plan.append(("local_contrast", AUTO_LOCAL_CONTRAST))

    return plan


def run_auto_plan(base, plan, settings: Settings, *, bg_runner=run_cli, rc_runner=run_cli,
                   on_progress=None) -> list[tuple[str, str, AstroImage]]:
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

    Returns a list of (step.name, serialized_option, image_after_step) per
    successfully-applied step -- the display name and a serialize_option()
    encoding (fine for recording/display; only the apply above must use the
    native option) so the caller can fold each stage into the live Project's
    editable history via Project.record_precomputed without recomputing the
    slow external-tool steps.

    Robust to a single stage failing (e.g. an external tool subprocess
    errors): that stage is skipped -- not recorded, image left unchanged --
    and the rest of the chain still runs. Never aborts the whole enhance."""
    from .tasks import Cancelled, current

    img = base
    n = len(plan)
    results: list[tuple[str, str, AstroImage]] = []
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
                black, _, _ = auto_levels(img.data)
                option = (black, 1.0, 1.0)
            result = step.apply(img, option)
        except Exception:
            if on_progress is not None:
                on_progress(i + 1, n, step.name)
            continue
        img = result
        results.append((step.name, serialize_option(stage_id, option), img))
        if on_progress is not None:
            on_progress(i + 1, n, step.name)
    return results
