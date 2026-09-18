from __future__ import annotations

from ..settings import (Settings, astap_valid, graxpert_valid, rcastro_valid,
                        resolve_binary, starnet_valid)
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro
from .background import BackgroundStep
from .ai_denoise import AiDenoiseStep
from .deconvolution_step import DeconvolutionStep
from .color import ColorStep
from .crop import CropStep
from .curves import CurvesStep
from .green_fringe import GreenFringeStep
from .levels import LevelsStep
from .local_contrast import LocalContrastStep
from .color_balance_step import ColorBalanceStep
from .narrowband_step import NarrowbandStep
from .noise_sharpen import NoiseSharpenStep
from .recover_core import RecoverCoreStep
from .remove_green_step import RemoveGreenStep
from .tint_step import TintStep
from .saturation_step import SaturationStep
from .star_reduction import StarReductionStep
from .stretch_step import StretchStep


def _splitter(settings: Settings):
    """The best available star/starless split, or None for the free fallback.

    RC-Astro first: the user paid for it and it is still the best. StarNet2
    second — free, and measurably far better than the fallback. Neither is
    required; `None` means core/starless.py, which never goes away.

    Five steps take this object and use it for nothing but splitting, so a
    StarNet is a drop-in wherever an RCAstro went. Steps that use RC-Astro for
    its OWN tools (denoise, deconvolution) keep taking a real RCAstro and are
    untouched by this.
    """
    if rcastro_valid(settings):
        return RCAstro(resolve_binary(settings.rcastro_path))
    if starnet_valid(settings):
        from ..tools.starnet import StarNet
        return StarNet(resolve_binary(settings.starnet_path))
    return None


def make_step(stage_id: str, settings: Settings, *, bg_runner=run_cli, rc_runner=run_cli):
    """Construct a processing step for a stage id, wiring GraXpert/RC-Astro from
    settings. Shared by the live app (MainWindow._step_for) and batch."""
    if stage_id == "crop":
        return CropStep()
    if stage_id in ("rotate", "flip_h", "flip_v"):
        return CropStep()  # geometry ops replay through the same engine
    if stage_id == "background":
        step = BackgroundStep(GraXpert(resolve_binary(settings.graxpert_path)))
        step._runner = bg_runner
        return step
    if stage_id == "color":
        from ..tools.astap import ASTAP
        from ..tools.gaia import query_field
        astap = ASTAP(resolve_binary(settings.astap_path)) if astap_valid(settings) else None
        return ColorStep(astap=astap, gaia_query=query_field)
    if stage_id == "tint":
        return TintStep()
    if stage_id == "remove_green":
        return RemoveGreenStep()
    if stage_id == "stretch":
        return StretchStep()
    if stage_id == "recover_core":
        return RecoverCoreStep()
    if stage_id == "levels":
        return LevelsStep()
    if stage_id == "curves":
        return CurvesStep()
    if stage_id == "saturation":
        step = SaturationStep(_splitter(settings))
        step._runner = rc_runner
        return step
    if stage_id == "green_fringe":
        step = GreenFringeStep(_splitter(settings))
        step._runner = rc_runner
        return step
    if stage_id == "local_contrast":
        return LocalContrastStep()
    if stage_id == "ai_denoise":
        return AiDenoiseStep()
    if stage_id == "deconvolution":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = DeconvolutionStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "noise_sharpen":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        gx = GraXpert(resolve_binary(settings.graxpert_path)) if graxpert_valid(settings) else None
        step = NoiseSharpenStep(rc, gx)
        step._runner = rc_runner
        return step
    if stage_id == "star_reduction":
        step = StarReductionStep(_splitter(settings))
        step._runner = rc_runner
        return step
    if stage_id == "color_balance":
        step = ColorBalanceStep(_splitter(settings))
        step._runner = rc_runner
        return step
    if stage_id == "narrowband":
        step = NarrowbandStep(_splitter(settings))
        step._runner = rc_runner
        return step
    raise ValueError(stage_id)
