from __future__ import annotations

import numpy as np

from ..settings import Settings, astap_valid, graxpert_valid, rcastro_valid
from .color import ColorSettings
from .crop import CropParams, detect_content_bounds
from .narrowband import NarrowbandParams


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
AUTO_BACKGROUND_STRENGTH = "light"  # provisional — tuned on real data (see plan Final): GraXpert extraction strength
AUTO_STRETCH_AMOUNT = 0.5        # provisional — tuned on real data (see plan Final): mid-slider stretch aggressiveness (see core/stretch.py amount_to_target)
AUTO_LEVELS = (0.0, 1.0, 1.0)    # provisional — tuned on real data (see plan Final): identity (black, gamma, white) until real-data tuning picks a bias
AUTO_SATURATION_AMOUNT = 0.6     # provisional — tuned on real data (see plan Final): native saturation slider amount (0.5 = neutral)
AUTO_SATURATION_NEBULA = 0.0     # provisional — tuned on real data (see plan Final): no starless nebula-boost by default (safe/cheap default)

AUTO_DENOISE_LIGHT = "light"     # provisional — tuned on real data (see plan Final)
AUTO_DENOISE_MEDIUM = "medium"   # provisional — tuned on real data (see plan Final)
AUTO_DENOISE_STRONG = "strong"   # provisional — tuned on real data (see plan Final)
AUTO_NOISE_LOW_THRESHOLD = 0.01  # provisional — tuned on real data (see plan Final): MAD proxy below this -> light denoise
AUTO_NOISE_HIGH_THRESHOLD = 0.05  # provisional — tuned on real data (see plan Final): MAD proxy above this -> strong denoise


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


def _noise_proxy(img) -> float:
    """Rough noise estimate: median absolute deviation of the raw data. Cheap
    and dependency-free; good enough to pick a denoise strength bucket."""
    data = img.data
    med = float(np.median(data))
    return float(np.median(np.abs(data - med)))


def _auto_denoise_option(img, settings: Settings) -> dict:
    """Engine picked by availability (RC-Astro NoiseXTerminator first, else
    GraXpert, else the built-in TV fallback baked into NoiseSharpenStep when
    engine is None); strength picked from a cheap noise proxy."""
    if rcastro_valid(settings):
        engine = "rcastro"
    elif graxpert_valid(settings):
        engine = "graxpert"
    else:
        engine = None
    proxy = _noise_proxy(img)
    if proxy > AUTO_NOISE_HIGH_THRESHOLD:
        level = AUTO_DENOISE_STRONG
    elif proxy < AUTO_NOISE_LOW_THRESHOLD:
        level = AUTO_DENOISE_LIGHT
    else:
        level = AUTO_DENOISE_MEDIUM
    return {"engine": engine, "level": level}


def build_auto_plan(img, settings: Settings, *, data_type: str | None = None) -> list[tuple[str, object]]:
    """Build (do not apply) the ordered one-tap enhance plan: a list of
    (stage_id, native_option) pairs matching steps/factory.py's stage_ids and
    recipe.py::serialize_option's native option types for each stage.

    Adaptive to the image (crop bounds, noise proxy) and to which external
    tools are installed (settings.*_valid). Never raises, even with a bare
    Settings() (nothing installed) -- background is simply omitted and
    denoise/color degrade to built-in engines. Deliberately excludes the more
    aggressive stages (deconvolution, star_reduction, green_fringe,
    local_contrast, curves, recover_core) for a balanced, natural default."""
    if data_type is None:
        data_type = detect_data_type(img.metadata)

    plan: list[tuple[str, object]] = [("crop", _auto_crop_option(img))]

    if graxpert_valid(settings):
        plan.append(("background", AUTO_BACKGROUND_STRENGTH))

    if data_type == "dualband":
        plan.append(("narrowband", NarrowbandParams()))
    else:
        method = "photometric" if astap_valid(settings) else "sky"
        plan.append(("color", ColorSettings(method=method)))
        plan.append(("stretch", AUTO_STRETCH_AMOUNT))

    plan.append(("levels", AUTO_LEVELS))
    plan.append(("noise_sharpen", _auto_denoise_option(img, settings)))
    plan.append(("saturation", (AUTO_SATURATION_AMOUNT, AUTO_SATURATION_NEBULA)))

    return plan
