from __future__ import annotations

from ..core.image import AstroImage
from ..core.noise import reduce_noise
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

_NXT_LEVELS = {"light": 0.75, "medium": 0.90, "strong": 0.95}  # RC-Astro NoiseXTerminator --denoise
_TV_LEVELS = {"light": 0.4, "medium": 0.7, "strong": 0.9}      # free TV fallback (unchanged)


class NoiseSharpenStep(Step):
    """Post-stretch denoise (NoiseXTerminator; free reduce_noise fallback).
    Sharpening/deconvolution is the separate Deconvolution step."""

    name = "Noise Reduction"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        if self._rc is not None:
            return self._rc.denoise(img, _NXT_LEVELS[option], runner=self._runner)
        return reduce_noise(img, _TV_LEVELS[option])
