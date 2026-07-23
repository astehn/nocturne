from __future__ import annotations

from ..settings import Settings, astap_valid, graxpert_valid, rcastro_valid, resolve_binary
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert
from ..tools.rcastro import RCAstro
from .background import BackgroundStep
from .deconvolution_step import DeconvolutionStep
from .color import ColorStep
from .crop import CropStep
from .curves import CurvesStep
from .green_fringe import GreenFringeStep
from .levels import LevelsStep
from .local_contrast import LocalContrastStep
from .narrowband_step import NarrowbandStep
from .noise_sharpen import NoiseSharpenStep
from .recover_core import RecoverCoreStep
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
        from ..tools.astap import ASTAP
        from ..tools.gaia import query_field
        astap = ASTAP(resolve_binary(settings.astap_path)) if astap_valid(settings) else None
        return ColorStep(astap=astap, gaia_query=query_field)
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
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = SaturationStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "green_fringe":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = GreenFringeStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "local_contrast":
        return LocalContrastStep()
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
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = StarReductionStep(rc)
        step._runner = rc_runner
        return step
    if stage_id == "narrowband":
        rc = RCAstro(resolve_binary(settings.rcastro_path)) if rcastro_valid(settings) else None
        step = NarrowbandStep(rc)
        step._runner = rc_runner
        return step
    raise ValueError(stage_id)
