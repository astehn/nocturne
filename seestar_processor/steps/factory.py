from __future__ import annotations

from ..settings import Settings, rcastro_valid, resolve_binary
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro
from .background import BackgroundStep
from .deconvolution_step import DeconvolutionStep
from .color import ColorStep
from .crop import CropStep
from .levels import LevelsStep
from .local_contrast import LocalContrastStep
from .noise_sharpen import NoiseSharpenStep
from .remove_green_step import RemoveGreenStep
from .saturation_step import SaturationStep
from .star_reduction import StarReductionStep
from .stretch_step import StretchStep


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
        return ColorStep()
    if stage_id == "remove_green":
        return RemoveGreenStep()
    if stage_id == "stretch":
        return StretchStep()
    if stage_id == "levels":
        return LevelsStep()
    if stage_id == "saturation":
        return SaturationStep()
    if stage_id == "local_contrast":
        return LocalContrastStep()
    if stage_id == "deconvolution":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = DeconvolutionStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "noise_sharpen":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = NoiseSharpenStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "star_reduction":
        step = StarReductionStep(RCAstro(resolve_binary(settings.rcastro_path)))
        step._runner = rc_runner
        return step
    raise ValueError(stage_id)
